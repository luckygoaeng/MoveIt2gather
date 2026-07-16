#!/usr/bin/env python3
#
# Session-start camera-to-arm calibration for OpenManipulator-X.
#
# The camera is remounted on a gooseneck clamp every session, so there is no
# fixed URDF transform for it. This node drives the arm through a few
# waypoints, records (TCP pose in "world", ArUco ID-0 marker pose in the
# camera frame) pairs, solves for the rigid transform between the two frames
# with the Kabsch algorithm, and publishes it as a static TF
# ("world" -> camera_frame). It keeps running afterward so that TF (a
# transient-local topic) stays available to late-joining subscribers such as
# pick_and_place_aruco.py.
#
# Reuses pick_and_place.py's MoveItPy setup and motion helpers rather than
# duplicating them - see that file for the planning/execution safety logic
# (plan() failure aborts before execute() is ever called).

import os
import sys
import time

from aruco_interfaces.msg import ArucoMarkers
import numpy as np
import rclpy
from rclpy.node import Node
from scipy.spatial.transform import Rotation
from tf2_ros import StaticTransformBroadcaster
from geometry_msgs.msg import TransformStamped

from open_manipulator_x_pick_place.pick_and_place import (
    ARM_GROUP,
    BASE_FRAME,
    EE_LINK,
    build_moveit_py,
    move_arm_to_joint_positions,
)

# Joint-space waypoints (joint1..joint4) the arm visits during calibration.
# Each one must be reachable and keep the gripper (ID-0 marker side) inside
# the camera's field of view. Measured via RViz drag + Execute + reading
# /joint_states, with ID 0 confirmed visible on /aruco_markers at each pose.
CALIBRATION_WAYPOINTS_JOINT_POSITIONS = [
    # [joint1, joint2, joint3, joint4]
    [-2.0694557179012918e-13, -1.000155473701645, 0.9986214929133457, -2.0694557179012918e-13],
    [-0.2868544073348218, -0.9295923574589056, 0.9587379924283184, -0.019941750242720158],
    [-0.2868544073348218, -0.44332044769915724, 0.8544272988520953, -0.07056311624294631],
    [0.48933987133531254, 0.18561167533395562, 0.299126253637493, -0.2577087723649947],
]

CALIBRATION_MARKER_ID = 0
MIN_WAYPOINTS_FOR_KABSCH = 3

# The ID-0 marker is stuck on the gripper body, not exactly at end_effector_link's
# origin. Measured by hand (torque off): ~8cm toward the wrist along
# end_effector_link's local +x axis (which points from link5 toward the
# gripper tip, rpy=0 relative to link5 - see open_manipulator_x.urdf). Without
# this correction, the physical offset rotates with the gripper across
# waypoints and corrupts the rigid-transform assumption Kabsch relies on.
MARKER_OFFSET_IN_EE_FRAME = np.array([-0.08, 0.0, 0.0])


def kabsch(src_points: np.ndarray, dst_points: np.ndarray):
    """Solve for R, t such that dst ~= R @ src + t (least squares, SVD-based)."""
    src_centroid = src_points.mean(axis=0)
    dst_centroid = dst_points.mean(axis=0)
    src_centered = src_points - src_centroid
    dst_centered = dst_points - dst_centroid

    h = src_centered.T @ dst_centered
    u, _, vt = np.linalg.svd(h)
    d = np.sign(np.linalg.det(vt.T @ u.T))
    correction = np.diag([1.0, 1.0, d])
    r = vt.T @ correction @ u.T
    t = dst_centroid - r @ src_centroid
    return r, t


class CalibrationNode(Node):

    def __init__(self):
        super().__init__('calibrate_camera_to_base')

        self.declare_parameter('camera_frame', 'camera_link')
        self.declare_parameter('markers_topic', '/aruco_markers')
        self.declare_parameter('settle_frames', 5)
        self.declare_parameter('marker_wait_timeout_sec', 8.0)

        self.camera_frame = self.get_parameter('camera_frame').get_parameter_value().string_value
        self.markers_topic = self.get_parameter('markers_topic').get_parameter_value().string_value
        self.settle_frames = self.get_parameter('settle_frames').get_parameter_value().integer_value
        self.marker_wait_timeout_sec = (
            self.get_parameter('marker_wait_timeout_sec').get_parameter_value().double_value
        )

        self._latest_markers = None
        self.create_subscription(
            ArucoMarkers, self.markers_topic, self._markers_callback, 10)
        self.tf_broadcaster = StaticTransformBroadcaster(self)

    def _markers_callback(self, msg: ArucoMarkers):
        self._latest_markers = msg

    def collect_calibration_marker_position(self):
        """Average CALIBRATION_MARKER_ID's position over settle_frames fresh
        messages. Returns None on timeout (marker not seen)."""
        samples = []
        deadline = time.monotonic() + self.marker_wait_timeout_sec
        while len(samples) < self.settle_frames and time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.2)
            msg = self._latest_markers
            self._latest_markers = None
            if msg is None:
                continue
            if CALIBRATION_MARKER_ID in msg.marker_ids:
                idx = list(msg.marker_ids).index(CALIBRATION_MARKER_ID)
                p = msg.poses[idx].position
                samples.append([p.x, p.y, p.z])
        if len(samples) < self.settle_frames:
            return None
        return np.mean(np.array(samples), axis=0)

    def publish_static_transform(self, rotation_matrix, translation):
        quat = Rotation.from_matrix(rotation_matrix).as_quat()  # x, y, z, w

        transform = TransformStamped()
        transform.header.stamp = self.get_clock().now().to_msg()
        transform.header.frame_id = BASE_FRAME
        transform.child_frame_id = self.camera_frame
        transform.transform.translation.x = float(translation[0])
        transform.transform.translation.y = float(translation[1])
        transform.transform.translation.z = float(translation[2])
        transform.transform.rotation.x = float(quat[0])
        transform.transform.rotation.y = float(quat[1])
        transform.transform.rotation.z = float(quat[2])
        transform.transform.rotation.w = float(quat[3])
        self.tf_broadcaster.sendTransform(transform)


def print_safety_banner():
    print('=' * 70)
    print('CAMERA-TO-ARM CALIBRATION - the real arm is about to move.')
    print('Make sure hands/face are clear of the arm workspace.')
    print('Velocity/acceleration scaling is limited to 0.2.')
    print('=' * 70)
    input('Press Enter to start calibration waypoints... ')


def main():
    if len(CALIBRATION_WAYPOINTS_JOINT_POSITIONS) < MIN_WAYPOINTS_FOR_KABSCH:
        print(
            f'CALIBRATION_WAYPOINTS_JOINT_POSITIONS has fewer than '
            f'{MIN_WAYPOINTS_FOR_KABSCH} entries - hand-teach waypoints and '
            'fill in the constant before running this node.',
            file=sys.stderr,
        )
        sys.exit(1)

    rclpy.init()
    node = CalibrationNode()
    logger = node.get_logger()

    moveit_py = build_moveit_py(node_name='calibrate_camera_to_base_moveit')
    arm = moveit_py.get_planning_component(ARM_GROUP)
    planning_scene_monitor = moveit_py.get_planning_scene_monitor()

    print_safety_banner()

    world_points = []
    camera_points = []

    for i, waypoint in enumerate(CALIBRATION_WAYPOINTS_JOINT_POSITIONS):
        step_name = f'calibration waypoint {i}'
        if not move_arm_to_joint_positions(moveit_py, arm, waypoint, step_name, logger):
            logger.error(f'{step_name}: planning/execution failed. Aborting calibration.')
            sys.stdout.flush()
            sys.stderr.flush()
            os._exit(1)

        with planning_scene_monitor.read_only() as scene:
            tcp_pose = scene.current_state.get_pose(EE_LINK)

        marker_position = node.collect_calibration_marker_position()
        if marker_position is None:
            logger.error(
                f'{step_name}: calibration marker (ID {CALIBRATION_MARKER_ID}) not seen '
                f'within {node.marker_wait_timeout_sec}s. Aborting calibration.'
            )
            sys.stdout.flush()
            sys.stderr.flush()
            os._exit(1)

        tcp_position = np.array(
            [tcp_pose.position.x, tcp_pose.position.y, tcp_pose.position.z])
        tcp_quat = [tcp_pose.orientation.x, tcp_pose.orientation.y,
                    tcp_pose.orientation.z, tcp_pose.orientation.w]
        tcp_rotation = Rotation.from_quat(tcp_quat).as_matrix()
        marker_true_position = tcp_position + tcp_rotation @ MARKER_OFFSET_IN_EE_FRAME

        world_points.append(marker_true_position.tolist())
        camera_points.append(marker_position.tolist())
        logger.info(
            f'{step_name}: recorded TCP={tcp_position.tolist()} '
            f'marker_true_world={world_points[-1]} marker_camera={camera_points[-1]}'
        )

    rotation_matrix, translation = kabsch(
        np.array(camera_points), np.array(world_points))
    node.publish_static_transform(rotation_matrix, translation)
    logger.info(
        f'Calibration complete. Publishing static TF "{BASE_FRAME}" -> '
        f'"{node.camera_frame}". Keeping this node alive so the transform '
        'stays available - do not close this terminal.'
    )

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass

    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


if __name__ == '__main__':
    main()

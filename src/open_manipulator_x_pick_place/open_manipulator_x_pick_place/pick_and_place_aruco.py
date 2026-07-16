#!/usr/bin/env python3
#
# ArUco-driven pick-and-place for OpenManipulator-X.
#
# Replaces Stage 2's hardcoded grasp coordinate with a live object marker
# (ID 1-4) read from /aruco/markers. Marker ID 0 is reserved for
# calibrate_camera_to_base.py and is always ignored here.
#
# One-shot design: waits for a single message containing at least one known
# object marker, snapshots it, and runs one pick-and-place sequence - it does
# not loop and re-trigger on its own. Requires calibrate_camera_to_base.py to
# already be running (it publishes the "world" -> camera_frame static TF this
# node looks up).
#
# Reuses pick_and_place.py's MoveItPy setup, motion helpers, and Stage 2's
# hand-taught place waypoints for marker ID 1 rather than duplicating them.

import os
import sys
import time

from aruco_interfaces.msg import ArucoMarkers
from geometry_msgs.msg import Pose, PoseStamped
from moveit.core.robot_state import RobotState
import numpy as np
import rclpy
from rclpy.node import Node
from tf2_ros import Buffer, TransformListener
import tf2_geometry_msgs  # noqa: F401  (registers PoseStamped transform support)

from open_manipulator_x_pick_place.pick_and_place import (
    ARM_GROUP,
    BASE_FRAME,
    EE_LINK,
    GRIPPER_CLOSE_STATE_NAME,
    GRIPPER_GROUP,
    GRIPPER_OPEN_STATE_NAME,
    HOME_STATE_NAME,
    LIFT_HEIGHT,
    PLACE_JOINT_POSITIONS,
    PRE_PLACE_JOINT_POSITIONS,
    build_moveit_py,
    move_arm_to_joint_positions,
    move_arm_to_named_state,
    move_gripper_to_named_state,
)

# SRDF "home" group_state for "arm" is all zeros (see open_manipulator_x.srdf).
HOME_SEED_JOINT_POSITIONS = np.array([0.0, 0.0, 0.0, 0.0])
IK_TIMEOUT_SEC = 0.1


def move_arm_to_pose_seeded(moveit_py, arm, position, step_name, logger):
    """Resolve a Cartesian target to a joint-space goal via IK seeded from
    home, then plan/execute in joint space.

    Stage 2 found that letting OMPL sample its own IK seeds for pose goals
    near this arm's base column can converge on self-colliding solutions for
    a target that IS reachable from a sensible seed (see PRE_PLACE/PLACE in
    pick_and_place.py, which hit the same issue and switched to joint-space
    goals). Camera-driven targets can't be hand-taught ahead of time, so
    solve IK explicitly here with a fixed, known-good seed instead of
    leaving seed selection to OMPL's pose-goal sampler.
    """
    pose = Pose()
    pose.position.x, pose.position.y, pose.position.z = position
    pose.orientation.w = 1.0

    seed_state = RobotState(moveit_py.get_robot_model())
    seed_state.set_joint_group_positions(ARM_GROUP, HOME_SEED_JOINT_POSITIONS)
    seed_state.update()

    if not seed_state.set_from_ik(ARM_GROUP, pose, EE_LINK, IK_TIMEOUT_SEC):
        logger.error(f'[{step_name}] IK failed to find a solution seeded from home.')
        return False

    joint_positions = seed_state.get_joint_group_positions(ARM_GROUP)
    return move_arm_to_joint_positions(moveit_py, arm, joint_positions, step_name, logger)

CALIBRATION_MARKER_ID = 0

# Marker id -> (pre-place joint positions, place joint positions). ID 1
# reuses Stage 2's hand-taught values. IDs 2-4 are placeholders - hand-teach
# them the same way (docs/guidebook.md section 5.5) before enabling that ID.
MARKER_ID_TO_PLACE_JOINT_POSITIONS = {
    1: (PRE_PLACE_JOINT_POSITIONS, PLACE_JOINT_POSITIONS),
    # 2: (PRE_PLACE_JOINT_POSITIONS_ID2, PLACE_JOINT_POSITIONS_ID2),
    # 3: (PRE_PLACE_JOINT_POSITIONS_ID3, PLACE_JOINT_POSITIONS_ID3),
    # 4: (PRE_PLACE_JOINT_POSITIONS_ID4, PLACE_JOINT_POSITIONS_ID4),
}

# Offset (meters, world frame z) between the object marker's own pose and the
# height the gripper should actually close at. Marker placement on the
# object determines this - tune empirically, same as Stage 2's LIFT_HEIGHT.
# -0.02: first physical grasp attempt at -0.05 grasped ~3cm too low - raised
# by 0.03 (pre-grasp rises by the same amount since it's grasp + LIFT_HEIGHT).
GRASP_Z_OFFSET = -0.02

# Empirical lateral correction (meters, world frame y): first physical grasp
# attempt landed ~3cm to the +y side of the object.
GRASP_Y_OFFSET = -0.03

# Empirical reach correction (meters, world frame x): gripper overshot ~3cm
# too far forward (away from the wrist) on the second attempt.
GRASP_X_OFFSET = -0.03


class ArucoPickAndPlaceNode(Node):

    def __init__(self):
        super().__init__('pick_and_place_aruco')

        self.declare_parameter('markers_topic', '/aruco_markers')
        self.declare_parameter('marker_wait_timeout_sec', 30.0)
        self.declare_parameter('settle_frames', 5)

        self.markers_topic = self.get_parameter('markers_topic').get_parameter_value().string_value
        self.marker_wait_timeout_sec = (
            self.get_parameter('marker_wait_timeout_sec').get_parameter_value().double_value
        )
        self.settle_frames = self.get_parameter('settle_frames').get_parameter_value().integer_value

        self._latest_markers = None
        self.create_subscription(
            ArucoMarkers, self.markers_topic, self._markers_callback, 10)

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

    def _markers_callback(self, msg: ArucoMarkers):
        self._latest_markers = msg

    def wait_for_object_marker(self, valid_ids):
        """Wait for valid_ids markers, then average each one's position over
        settle_frames consecutive detections (noise reduction, same approach
        calibrate_camera_to_base.py uses for the ID-0 marker).

        Locks onto whichever ids are present in the first matching message -
        markers that only appear later are ignored for this call.

        Returns (header, [(marker_id, averaged_pose), ...]) in id order, or
        (None, []) on timeout.
        """
        deadline = time.monotonic() + self.marker_wait_timeout_sec
        target_ids = None
        position_samples = {}
        last_pose = {}
        last_header = None

        while time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.2)
            msg = self._latest_markers
            self._latest_markers = None
            if msg is None:
                continue

            present = {
                marker_id: pose
                for marker_id, pose in zip(msg.marker_ids, msg.poses)
                if marker_id in valid_ids
            }
            if not present:
                continue

            if target_ids is None:
                target_ids = set(present.keys())
                for marker_id in target_ids:
                    position_samples[marker_id] = []

            last_header = msg.header
            for marker_id, pose in present.items():
                if marker_id in position_samples:
                    position_samples[marker_id].append(
                        [pose.position.x, pose.position.y, pose.position.z])
                    last_pose[marker_id] = pose

            if all(len(position_samples[m]) >= self.settle_frames for m in target_ids):
                break

        if target_ids is None:
            return None, []

        candidates = []
        for marker_id in sorted(target_ids):
            samples = position_samples[marker_id]
            if not samples:
                continue
            averaged = np.mean(np.array(samples), axis=0)
            pose = Pose()
            pose.position.x, pose.position.y, pose.position.z = averaged.tolist()
            pose.orientation = last_pose[marker_id].orientation
            candidates.append((marker_id, pose))

        return last_header, candidates

    def transform_pose_to_world(self, header, pose):
        pose_stamped = PoseStamped()
        pose_stamped.header = header
        pose_stamped.pose = pose

        # Buffer.can_transform()/transform() only busy-sleep on their
        # timeout - they never spin this node's executor, so a TF that
        # hasn't been received *yet* (e.g. calibrate_camera_to_base's
        # world->camera_frame static transform) can never arrive while
        # waiting inside them. Spin manually until it's available first.
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if self.tf_buffer.can_transform(BASE_FRAME, header.frame_id, header.stamp):
                break
            rclpy.spin_once(self, timeout_sec=0.1)
        else:
            self.get_logger().warn(
                f'TF "{BASE_FRAME}" <- "{header.frame_id}" never became available. '
                'Is calibrate_camera_to_base running?'
            )
            return None

        try:
            return self.tf_buffer.transform(pose_stamped, BASE_FRAME)
        except Exception as exc:
            self.get_logger().warn(f'TF transform to "{BASE_FRAME}" failed: {exc}')
            return None


def run_pick_and_place_for_marker(moveit_py, arm, gripper, marker_id, world_pose, logger):
    grasp_x = world_pose.pose.position.x + GRASP_X_OFFSET
    grasp_y = world_pose.pose.position.y + GRASP_Y_OFFSET
    grasp_z = world_pose.pose.position.z + GRASP_Z_OFFSET
    grasp_position = (grasp_x, grasp_y, grasp_z)
    pre_grasp_position = (
        grasp_position[0], grasp_position[1], grasp_position[2] + LIFT_HEIGHT)

    prefix = f'marker {marker_id}'
    logger.info(
        f'{prefix}: world-frame grasp target = {grasp_position}, '
        f'pre-grasp = {pre_grasp_position} (world pose from TF: '
        f'x={world_pose.pose.position.x:.4f} y={world_pose.pose.position.y:.4f} '
        f'z={world_pose.pose.position.z:.4f})'
    )

    # KDL's numerical IK seeds from the current joint state, so planning to a
    # Cartesian pose goal from an arbitrary starting pose (e.g. wherever the
    # last calibration waypoint left the arm) can fail to converge even for a
    # genuinely reachable target. Stage 2 always started its sequence from
    # "home" - match that here rather than planning from whatever pose we
    # happen to be in.
    if not move_arm_to_named_state(moveit_py, arm, HOME_STATE_NAME, f'{prefix}: home (pre-attempt)', logger):
        logger.error(f'{prefix}: failed to reach home before attempting grasp. Aborting.')
        return False

    if not move_arm_to_pose_seeded(moveit_py, arm, pre_grasp_position, f'{prefix}: pre-grasp', logger):
        logger.warn(f'{prefix}: pre-grasp unreachable, skipping this marker.')
        return None  # signal "try next candidate", not a hard failure

    place_pre, place_final = MARKER_ID_TO_PLACE_JOINT_POSITIONS[marker_id]

    steps = [
        (f'{prefix}: grasp (descend)', lambda: move_arm_to_pose_seeded(
            moveit_py, arm, grasp_position, f'{prefix}: grasp (descend)', logger)),
        (f'{prefix}: gripper close', lambda: move_gripper_to_named_state(
            moveit_py, gripper, GRIPPER_CLOSE_STATE_NAME, f'{prefix}: gripper close', logger)),
        (f'{prefix}: lift', lambda: move_arm_to_pose_seeded(
            moveit_py, arm, pre_grasp_position, f'{prefix}: lift', logger)),
        (f'{prefix}: pre-place', lambda: move_arm_to_joint_positions(
            moveit_py, arm, place_pre, f'{prefix}: pre-place', logger)),
        (f'{prefix}: place (descend)', lambda: move_arm_to_joint_positions(
            moveit_py, arm, place_final, f'{prefix}: place (descend)', logger)),
        (f'{prefix}: gripper open', lambda: move_gripper_to_named_state(
            moveit_py, gripper, GRIPPER_OPEN_STATE_NAME, f'{prefix}: gripper open', logger)),
        (f'{prefix}: retreat', lambda: move_arm_to_joint_positions(
            moveit_py, arm, place_pre, f'{prefix}: retreat', logger)),
        (f'{prefix}: home', lambda: move_arm_to_named_state(
            moveit_py, arm, HOME_STATE_NAME, f'{prefix}: home', logger)),
    ]

    for step_name, step_fn in steps:
        logger.info(f'=== starting step: {step_name} ===')
        if not step_fn():
            # Object may already be grasped at this point - do not try
            # another marker, stop the whole run (same as Stage 2).
            logger.error(f'Pick-and-place sequence aborted at step: {step_name}')
            return False

    logger.info(f'{prefix}: pick-and-place sequence completed successfully.')
    return True


def main():
    valid_ids = sorted(MARKER_ID_TO_PLACE_JOINT_POSITIONS.keys())
    if not valid_ids:
        print(
            'MARKER_ID_TO_PLACE_JOINT_POSITIONS has no entries - hand-teach '
            'at least one place location and fill in the mapping before '
            'running this node.',
            file=sys.stderr,
        )
        sys.exit(1)
    assert CALIBRATION_MARKER_ID not in valid_ids, (
        'Calibration marker id must never be in the object destination map.')

    rclpy.init()
    node = ArucoPickAndPlaceNode()
    logger = node.get_logger()

    moveit_py = build_moveit_py(node_name='pick_and_place_aruco_moveit')
    arm = moveit_py.get_planning_component(ARM_GROUP)
    gripper = moveit_py.get_planning_component(GRIPPER_GROUP)

    logger.info(f'Waiting for an object marker with id in {valid_ids} on {node.markers_topic}...')
    header, candidates = node.wait_for_object_marker(valid_ids)
    if not candidates:
        logger.error(
            f'No object marker detected within {node.marker_wait_timeout_sec}s. Exiting.')
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(1)

    success = False
    for marker_id, marker_pose in candidates:
        world_pose = node.transform_pose_to_world(header, marker_pose)
        if world_pose is None:
            continue

        result = run_pick_and_place_for_marker(
            moveit_py, arm, gripper, marker_id, world_pose, logger)
        if result is None:
            continue  # pre-grasp unreachable - try next candidate marker
        success = result
        break  # committed to a grasp attempt - stop after this one either way

    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0 if success else 1)


if __name__ == '__main__':
    main()

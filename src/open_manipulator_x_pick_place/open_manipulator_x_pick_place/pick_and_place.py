#!/usr/bin/env python3
#
# Fixed-pose pick-and-place sequence for OpenManipulator-X.
#
# Runs its own embedded moveit_py planning pipeline (MoveItPy), not a client
# of the already-running move_group node. Don't use RViz Plan/Execute while
# this script is running - both would send goals to the same
# arm_controller/gripper_controller.

import os
from pathlib import Path
import sys
import time

from geometry_msgs.msg import PoseStamped
from moveit.core.robot_state import RobotState
from moveit.planning import MoveItPy, PlanRequestParameters
from moveit_configs_utils import MoveItConfigsBuilder
import numpy as np
import rclpy
from rclpy.logging import get_logger

ROBOT_NAME = 'open_manipulator_x'
MOVEIT_CONFIG_PACKAGE = 'open_manipulator_moveit_config'

ARM_GROUP = 'arm'
GRIPPER_GROUP = 'gripper'

# Named group states already defined in open_manipulator_x.srdf.
HOME_STATE_NAME = 'home'
GRIPPER_OPEN_STATE_NAME = 'open'
GRIPPER_CLOSE_STATE_NAME = 'close'

# kinematics.yaml sets position_only_ik: True for "arm", so orientation in
# pose goals below is ignored - only x/y/z matter.
BASE_FRAME = 'world'
EE_LINK = 'end_effector_link'

# Measured on the real arm via tf2_echo (torque disabled for hand-teaching).
LIFT_HEIGHT = 0.08  # meters added to grasp/place z for the "above" waypoints

GRASP_POSITION = (0.20, 0.00, 0.05)
PRE_GRASP_POSITION = (
    GRASP_POSITION[0], GRASP_POSITION[1], GRASP_POSITION[2] + LIFT_HEIGHT)

# Joint-space goals rather than Cartesian pose goals for pre-place/place:
# "arm" has 1 redundant DOF under position-only IK, and OMPL's IK sampling
# for a pose goal here kept converging on self-colliding solutions even
# though the pose is physically reachable. Values read from /joint_states
# while hand-teaching the real arm; order is joint1, joint2, joint3, joint4.
PRE_PLACE_JOINT_POSITIONS = [
    -0.5184855063055536, -0.42951462060818635, 0.9756117810950604, -0.5752427954573225
]
PLACE_JOINT_POSITIONS = [
    -0.5491651220632665, -0.09203884727334533, 1.2225826879446489, -1.1152040327930681
]

MAX_VELOCITY_SCALING_FACTOR = 0.2
MAX_ACCELERATION_SCALING_FACTOR = 0.2

# Lets the planning scene monitor's current-state tracking catch up with
# the real robot after execute() before the next plan() call.
STATE_SETTLE_DELAY_SEC = 0.5


def build_moveit_py(node_name: str) -> MoveItPy:
    moveit_config = (
        MoveItConfigsBuilder(robot_name=ROBOT_NAME, package_name=MOVEIT_CONFIG_PACKAGE)
        .robot_description_semantic(
            str(Path('config') / ROBOT_NAME / f'{ROBOT_NAME}.srdf'))
        .joint_limits(str(Path('config') / ROBOT_NAME / 'joint_limits.yaml'))
        .trajectory_execution(
            str(Path('config') / ROBOT_NAME / 'moveit_controllers.yaml'))
        .robot_description_kinematics(
            str(Path('config') / ROBOT_NAME / 'kinematics.yaml'))
        .to_dict()
    )
    # moveit_py's embedded MoveItCpp expects "planning_pipelines" nested
    # under "pipeline_names", unlike move_group's flat list format. Reshape
    # here only - move_group's own parameters are untouched.
    moveit_config['planning_pipelines'] = {
        'pipeline_names': moveit_config['planning_pipelines']
    }
    # Default kinematics_solver_timeout (5ms) is too short for KDL's
    # numerical IK to converge reliably on this 4-DOF position-only chain.
    # Override here only; the yaml file is untouched.
    moveit_config['robot_description_kinematics']['arm']['kinematics_solver_timeout'] = 0.05
    return MoveItPy(node_name=node_name, config_dict=moveit_config)


def build_pose_goal(position) -> PoseStamped:
    x, y, z = position
    pose = PoseStamped()
    pose.header.frame_id = BASE_FRAME
    pose.pose.position.x = x
    pose.pose.position.y = y
    pose.pose.position.z = z
    pose.pose.orientation.w = 1.0
    return pose


def plan_and_execute(moveit_py, planning_component, group_name, step_name, logger):
    logger.info(f'[{step_name}] planning...')
    planning_component.set_start_state_to_current_state()

    # These fields default to empty/zero unless declared under
    # "<group>.plan_request_params.*" in config, which we don't have here -
    # set explicitly instead of relying on config defaults.
    plan_params = PlanRequestParameters(moveit_py, group_name)
    plan_params.planning_pipeline = 'ompl'
    plan_params.planner_id = 'RRTConnect'
    plan_params.planning_time = 5.0
    plan_params.planning_attempts = 5
    plan_params.max_velocity_scaling_factor = MAX_VELOCITY_SCALING_FACTOR
    plan_params.max_acceleration_scaling_factor = MAX_ACCELERATION_SCALING_FACTOR

    plan_result = planning_component.plan(single_plan_parameters=plan_params)
    if not plan_result:
        logger.error(
            f'[{step_name}] planning FAILED (error_code={plan_result.error_code}). '
            'Stopping sequence - real arm will not move for this step.'
        )
        return False

    logger.info(f'[{step_name}] planning succeeded, executing...')
    execution_status = moveit_py.execute(plan_result.trajectory, controllers=[])
    status_str = str(execution_status.status)
    if 'SUCCEEDED' not in status_str:
        logger.error(f'[{step_name}] execution FAILED (status={status_str}). Stopping sequence.')
        return False

    time.sleep(STATE_SETTLE_DELAY_SEC)

    logger.info(f'[{step_name}] done.')
    return True


def move_arm_to_named_state(moveit_py, arm, state_name, step_name, logger):
    arm.set_goal_state(configuration_name=state_name)
    return plan_and_execute(moveit_py, arm, ARM_GROUP, step_name, logger)


def move_arm_to_joint_positions(moveit_py, arm, joint_positions, step_name, logger):
    goal_state = RobotState(moveit_py.get_robot_model())
    goal_state.set_joint_group_positions(ARM_GROUP, np.array(joint_positions, dtype=np.float64))
    goal_state.update()
    arm.set_goal_state(robot_state=goal_state)
    return plan_and_execute(moveit_py, arm, ARM_GROUP, step_name, logger)


def move_arm_to_pose(moveit_py, arm, position, step_name, logger):
    arm.set_goal_state(pose_stamped_msg=build_pose_goal(position), pose_link=EE_LINK)
    return plan_and_execute(moveit_py, arm, ARM_GROUP, step_name, logger)


def move_gripper_to_named_state(moveit_py, gripper, state_name, step_name, logger):
    gripper.set_goal_state(configuration_name=state_name)
    return plan_and_execute(moveit_py, gripper, GRIPPER_GROUP, step_name, logger)


def run_pick_and_place(moveit_py, logger):
    arm = moveit_py.get_planning_component(ARM_GROUP)
    gripper = moveit_py.get_planning_component(GRIPPER_GROUP)

    steps = [
        ('1. home', lambda: move_arm_to_named_state(
            moveit_py, arm, HOME_STATE_NAME, '1. home', logger)),
        ('2. pre-grasp', lambda: move_arm_to_pose(
            moveit_py, arm, PRE_GRASP_POSITION, '2. pre-grasp', logger)),
        ('3. grasp (descend)', lambda: move_arm_to_pose(
            moveit_py, arm, GRASP_POSITION, '3. grasp (descend)', logger)),
        ('4. gripper close', lambda: move_gripper_to_named_state(
            moveit_py, gripper, GRIPPER_CLOSE_STATE_NAME, '4. gripper close', logger)),
        ('5. lift', lambda: move_arm_to_pose(
            moveit_py, arm, PRE_GRASP_POSITION, '5. lift', logger)),
        ('6. pre-place', lambda: move_arm_to_joint_positions(
            moveit_py, arm, PRE_PLACE_JOINT_POSITIONS, '6. pre-place', logger)),
        ('7. place (descend)', lambda: move_arm_to_joint_positions(
            moveit_py, arm, PLACE_JOINT_POSITIONS, '7. place (descend)', logger)),
        ('8. gripper open', lambda: move_gripper_to_named_state(
            moveit_py, gripper, GRIPPER_OPEN_STATE_NAME, '8. gripper open', logger)),
        ('9. retreat', lambda: move_arm_to_joint_positions(
            moveit_py, arm, PRE_PLACE_JOINT_POSITIONS, '9. retreat', logger)),
        ('9. home', lambda: move_arm_to_named_state(
            moveit_py, arm, HOME_STATE_NAME, '9. home', logger)),
    ]

    for step_name, step_fn in steps:
        logger.info(f'=== starting step: {step_name} ===')
        if not step_fn():
            logger.error(f'Pick-and-place sequence aborted at step: {step_name}')
            return False

    logger.info('Pick-and-place sequence completed successfully.')
    return True


def main():
    rclpy.init()
    logger = get_logger('open_manipulator_x_pick_place')

    moveit_py = build_moveit_py(node_name='pick_and_place')
    success = run_pick_and_place(moveit_py, logger)

    # moveit_py's shutdown()/destructor segfaults on this install (known
    # upstream issue) - skip it and exit directly instead of letting Python
    # run the crashing teardown path.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0 if success else 1)


if __name__ == '__main__':
    main()

from dataclasses import dataclass, field

from lerobot.cameras import CameraConfig
from lerobot.cameras.opencv import OpenCVCameraConfig
from lerobot.robots import RobotConfig
from lerobot_robot_ros.config import ActionType, GripperActionType, ROS2Config, ROS2InterfaceConfig

# Joint position limits from open_manipulator_x_arm.urdf.xacro (radians for joint1-4,
# meters for the gripper). Gripper open/close values match the SRDF "open"/"close"
# group states in open_manipulator_x.srdf.
ARM_JOINT_NAMES = ["joint1", "joint2", "joint3", "joint4"]
ARM_MIN_POSITIONS = [-3.14159, -1.5, -1.5, -1.7]
ARM_MAX_POSITIONS = [3.14159, 1.5, 1.4, 1.97]
GRIPPER_JOINT_NAME = "gripper_left_joint"
GRIPPER_OPEN_POSITION = 0.019
GRIPPER_CLOSE_POSITION = -0.01

# Conservative per-step clamp for zero-shot policy rollout (radians). Tune upward
# after the first supervised test run.
MAX_RELATIVE_TARGET = 0.1


@RobotConfig.register_subclass("open_manipulator_x")
@dataclass
class OpenManipulatorXConfig(ROS2Config):
    action_type: ActionType = ActionType.JOINT_TRAJECTORY

    max_relative_target: float | None = MAX_RELATIVE_TARGET

    cameras: dict[str, CameraConfig] = field(
        default_factory=lambda: {
            "overhead": OpenCVCameraConfig(index_or_path=0, width=1280, height=720, fps=10),
        }
    )

    ros2_interface: ROS2InterfaceConfig = field(
        default_factory=lambda: ROS2InterfaceConfig(
            arm_joint_names=ARM_JOINT_NAMES,
            gripper_joint_name=GRIPPER_JOINT_NAME,
            # root link of open_manipulator_x.urdf is "world", not "base_link".
            # Only used for ActionType.CARTESIAN_VELOCITY, which we don't use here.
            base_link="world",
            min_joint_positions=ARM_MIN_POSITIONS,
            max_joint_positions=ARM_MAX_POSITIONS,
            gripper_open_position=GRIPPER_OPEN_POSITION,
            gripper_close_position=GRIPPER_CLOSE_POSITION,
            gripper_action_type=GripperActionType.ACTION,
        )
    )

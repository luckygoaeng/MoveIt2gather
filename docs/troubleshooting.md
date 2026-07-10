# 트러블슈팅

Stage 1(브링업/텔레옵)과 Stage 2(MoveIt2 pick-and-place) 진행 중 실제로 겪은 에러와 해결법입니다. 증상으로 `Ctrl+F` 검색해서 찾아보세요.

## Stage 1 — 환경 세팅 / 브링업

| 증상 | 원인 | 해결 |
| --- | --- | --- |
| OpenCR 업로드 시 `arm-none-eabi-g++: no such file or directory` | Ubuntu 24.04(Noble)에서 매뉴얼의 `libncurses5-dev:i386` 패키지 미제공. 파일은 있는데 32비트 동적 링커가 없음 | `sudo dpkg --add-architecture i386` 후 `libc6:i386 libncurses6:i386 libstdc++6:i386` 설치 |
| Arduino IDE 첫 실행 시 `FATAL: setuid_sandbox_host.cc(158)] The SUID sandbox helper binary was found, but is not configured correctly` | Arduino IDE 2.x AppImage의 샌드박스 설정 문제 | `./arduino-ide --no-sandbox` 옵션으로 실행 (alias 등록 권장) |
| ROS2 통신 시 `[TxRxResult] There is no status packet!` | OpenCR에 `usb_to_dxl` 펌웨어가 업로드되지 않은 상태 | Arduino IDE에서 `File → Examples → OpenCR → 10.Etc → usb_to_dxl` 업로드 |
| 브링업 시 `Error opening serial port!` 반복 | `open_manipulator_x.launch.py`의 `port_name` 기본값이 U2D2용(`/dev/ttyUSB0`). OpenCR은 `/dev/ttyACM0` | 브링업 명령에 `port_name:=/dev/ttyACM0` 명시 |
| `rosdep install`이 로컬 소스 패키지를 인식 못 함 | 클론한 패키지(DynamixelSDK 등)가 rosdep DB에 없음 | `--skip-keys="librealsense2 dynamixel_hardware_interface dynamixel_interfaces dynamixel_sdk open_manipulator robotis_interfaces"` 추가 |
| OpenCR 업로드 실패 | 보드가 정상 응답 안 함 | Recovery Mode 진입: 전원 ON → `PUSH SW2` 누른 채 `Reset` 눌렀다 떼기 → `PUSH SW2` 떼기. STATUS LED 100ms 간격 점멸 확인 |

## Stage 1 부가 — Ubuntu 계정 표준화 시 (랩 공용 세팅)

| 증상 | 원인 | 해결 |
| --- | --- | --- |
| GDM 로그인 화면에 옛날 이름이 뜸 | GDM은 로그인명이 아니라 GECOS(Full Name) 필드를 표시 | `sudo usermod -c "새이름" $USER` |
| 계정 rename 후 Chrome이 인터넷 연결 불가처럼 나옴 | Chrome Singleton lock 파일이 옛 호스트명을 참조 | `~/.config/google-chrome/Singleton*` 삭제 |
| 계정 rename 후 ROS2 빌드 에러 | 빌드 아티팩트에 절대경로가 하드코딩되어 있음 | `rm -rf build install log && colcon build` |

## Stage 2 — MoveIt2 Pick-and-Place (`moveit_py`)

실제로 겪은 순서대로 정리했습니다.

| # | 증상 | 원인 | 해결 |
| --- | --- | --- | --- |
| 1 | `RuntimeError: Failed to load planning pipelines from parameter server` | `MoveItConfigsBuilder`가 만드는 `planning_pipelines`는 move_group용 평평한 리스트(`['ompl', ...]`)인데, `moveit_py`의 `MoveItCpp`는 같은 파라미터를 `{'pipeline_names': [...]}` 중첩 구조로 기대함 | 스크립트 안에서 `moveit_config['planning_pipelines'] = {'pipeline_names': [...]}`로 재구성 (yaml 파일은 안 건드림) |
| 2 | `No planning pipeline available for name ''` | `PlanRequestParameters`가 `<group>.plan_request_params.*` 네임스페이스에서 기본값(플래너·파이프라인 이름)을 읽으려는데 config에 없어서 전부 빈 값 | `plan_params.planning_pipeline='ompl'`, `planner_id='RRTConnect'` 등 코드에서 직접 지정 |
| 3 | `Segmentation fault` (스크립트 종료 시) | `moveit_py.shutdown()`(C++ 소멸자)의 알려진 업스트림 버그. 실물 팔 동작과는 무관 — plan 실패를 정확히 감지하고 안전하게 멈춘 뒤 발생 | 정상 종료 로직 대신 `os._exit()`로 프로세스 강제 종료 |
| 4 | `Action client not connected to action server: arm_controller/follow_joint_trajectory` | bringup(컨트롤러 매니저)이 안 떠 있거나 컨트롤러가 아직 active 아님 | bringup 켜진 상태 확인 후 재실행 |
| 5 | `Unable to sample any valid states for goal tree` (IK 실패) | 좌표가 실제로 도달 불가능한 위치(placeholder 예시값)였음 | RViz Plan으로 먼저 도달 가능 여부 확인 후 좌표 결정, 또는 수동교시로 실측 |
| 6 | 수동교시로 실측한 좌표인데도 같은 IK 실패 | `arm` 그룹은 position-only IK(3값 목표에 4관절 → 여유자유도 1개)라 같은 XYZ에 도달하는 관절 조합이 여러 개 존재. OMPL의 랜덤 IK 샘플링이 손으로 배치했던 충돌 없는 조합이 아니라 **자기충돌하는 다른 조합**으로 계속 수렴 | 좌표(Cartesian) 목표 대신 **관절값(joint-space) 목표**로 전환 — `RobotState.set_joint_group_positions()`로 검증된 관절값을 직접 지정, IK 재탐색 생략 |
| 7 | `Invalid Trajectory: start point deviates from current robot state more than 0.01` | 직전 스텝 실행 직후 planning scene monitor의 상태 캐시가 실제 로봇 상태를 아직 못 따라와서, 다음 planning이 오래된 상태를 기준으로 계산됨 | 매 스텝 실행 후 `time.sleep(0.5)`로 상태 안정 시간 확보 |
| 8 | 그리퍼가 안 움직이는 것처럼 보임 (오탐) | 그리퍼가 이미 close 상태에서 다시 close 명령 → 물리적 변화 없어서 안 움직인 것처럼 보였을 뿐 | `moveit_py`를 완전히 배제하고 컨트롤러 직접 테스트로 정상 동작 확인 (아래 진단 명령 참고) |

### Stage 2 진단에 쓴 명령어 모음

```bash
# 컨트롤러 상태 확인
ros2 control list_controllers

# 그리퍼 액션 서버 확인
ros2 action list | grep gripper

# moveit_py/스크립트를 완전히 배제하고 컨트롤러 직접 테스트
ros2 action send_goal /gripper_controller/gripper_cmd control_msgs/action/GripperCommand \
  "{command: {position: -0.01, max_effort: 0.0}}"

# 관절 상태 실시간 확인
ros2 topic echo /joint_states
```

## Stage 2 — 하드웨어 이슈

### 그리퍼 open/close 방향 반전

**증상**: GUI/MoveIt/teleop 등 그리퍼를 제어하는 모든 경로에서 `open` 명령 시 실제로는 닫히고, `close` 명령 시 열림.

**진단**: GUI(`main_window.cpp`), MoveIt SRDF(`open_manipulator_x.srdf`), URDF(`open_manipulator_x_arm.urdf.xacro`) 세 곳 모두 "양수 값 = open"으로 일치 — 소프트웨어 쪽 의미 정의는 문제 없음. 근본 원인은 **조립 시 그리퍼 구동 모터가 설계 기준과 반대 방향으로 장착**된 것.

**조치**: `dynamixel_hardware_interface`에서 raw encoder 값을 미터 단위로 변환하는 최하단 레이어 수정. 파일: `src/open_manipulator/open_manipulator_description/ros2_control/open_manipulator_x_position.ros2_control.xacro` (dxl5 / 그리퍼, ID 15) — `[unit info]`의 multiplier·offset 부호를 전부 반전.

```diff
- Present Position,0.000017626621790,m,signed,-0.036099321;
- Goal Position,0.000017626621790,m,signed,-0.036099321;
- Present Velocity,0.000275558153557,rad/s,signed,0.0;
- Goal Velocity,0.000275558153557,rad/s,signed,0.0;
+ Present Position,-0.000017626621790,m,signed,0.036099321;
+ Goal Position,-0.000017626621790,m,signed,0.036099321;
+ Present Velocity,-0.000275558153557,rad/s,signed,0.0;
+ Goal Velocity,-0.000275558153557,rad/s,signed,0.0;
```

`값 = raw × multiplier + offset` 변환식에서 multiplier·offset을 동시에 음수로 뒤집으면 물리적 가동범위는 유지한 채 "이 값이 open이냐 close냐"라는 라벨만 교정됩니다. 다이나믹셀 펌웨어 레벨의 `Drive Mode`(reverse bit)는 원점(zero) 보정과 얽혀 재-homing이 필요할 위험이 있어 건드리지 않고, ROS 드라이버 쪽 소프트웨어 변환식만 수정했습니다. GUI/MoveIt SRDF의 `open=0.019`, `close=-0.01` 값은 수정 없이 그대로 사용 가능합니다.

**검증**: 새 로봇(아래 이슈로 교체된 개체)에서 GUI open/close 버튼 정상 동작 확인 완료.

### 브링업 중 통신 끊김 / 발열 (배선 이슈, 코드와 무관)

**증상**: 팔이 움직이기 시작하면 `FastSyncRead Rx Fail COMM_RX_TIMEOUT(-3001)`이 5축 전체에서 반복 발생, 컨트롤러 강제 비활성화. 기체 발열 동반.

**원인**: 1축(joint1) 근처 전선이 관절에 여러 번 감겨 끼어 있었고, 반복 구동 중 피복이 벗겨지며 부하 발생 → 통신 불안정 + 발열.

**조치**: 로봇 교체로 해결. (5축 전체가 동시에 응답 끊기는 패턴이라 그리퍼 unit info 값과는 다른 레이어의 문제였음 — 코드 수정과 무관)

## 일반 참고

- `emanual.robotis.com` 문서는 일부 outdated 되어 있으므로 실제 패키지 소스 및 실험으로 교차 검증이 필요합니다.
- 반나절 넘게 혼자 막히면 에러 메시지를 통째로 복사해서 바로 질문하세요.

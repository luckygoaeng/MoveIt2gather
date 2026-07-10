# 재현 가이드북 — OpenManipulator-X 텔레오퍼레이션 & MoveIt2 Pick-and-Place

이 문서만 보고 따라 하면 **환경 세팅부터 MoveIt2로 물체를 집어 옮기는 것까지** 재현할 수 있습니다.
에러가 나면 먼저 [troubleshooting.md](./troubleshooting.md)에서 증상을 검색해 보세요.

- **대상 하드웨어**: OpenManipulator-X (4축), OpenCR 제어보드
- **소프트웨어**: Ubuntu 24.04 LTS, ROS 2 Jazzy Jalisco, MoveIt 2
- **완료 상태**: Stage 1 (텔레오퍼레이션) ✅ · Stage 2 (MoveIt2 pick-and-place) ✅

---

## 0. 완료 체크리스트

- [ ] Ubuntu 24.04 + ROS 2 Jazzy 설치
- [ ] MoveIt2 + `moveit_py` 설치
- [ ] ROBOTIS 패키지 4종 클론 & 빌드
- [ ] OpenCR에 `usb_to_dxl` 펌웨어 업로드
- [ ] 브링업 성공 (`/joint_states` 발행 확인)
- [ ] 키보드 텔레오퍼레이션 동작 확인
- [ ] RViz MoveIt 플러그인으로 Plan/Execute 성공
- [ ] `moveit_py` 스크립트로 pick-and-place 9단계 시퀀스 성공

---

## 1. 환경 세팅

### 1.1 OS & ROS 2

- Ubuntu 24.04 LTS 설치 (Rufus로 USB 부팅 디스크 생성 후 설치)
- ROS 2 Jazzy Jalisco 설치: [공식 문서](https://docs.ros.org/en/jazzy/Installation.html)

### 1.2 MoveIt2 설치

```bash
sudo apt update
sudo apt install ros-jazzy-moveit ros-jazzy-dynamixel-sdk
sudo apt install -y ros-jazzy-moveit-py
```

> ⚠️ `ros-jazzy-moveit-py`는 `ros-jazzy-moveit` 메타패키지에 포함되지 **않는 별도 apt 패키지**입니다. Stage 2 스크립트(`from moveit.planning import MoveItPy`)를 쓰려면 반드시 따로 설치해야 합니다. 설치 후 워크스페이스를 다시 source 하세요.

### 1.3 로봇팔 연결 확인

- 사용 보드: **OpenCR** (U2D2 아님)
- 라즈베리파이5에 연결된 포트 확인:
  ```bash
  ls /dev/ttyACM*
  # 예: /dev/ttyACM0
  ```
- 포트 권한 문제 시:
  ```bash
  sudo usermod -aG dialout $USER
  # 로그아웃/재로그인 또는 재부팅 필요
  ```

---

## 2. ROS 패키지 설치 (ROBOTIS 공식)

참고: [OpenManipulator-X Quick Start Guide](https://emanual.robotis.com/docs/en/platform/openmanipulator_x/quick_start_guide/#install-ros-packages)

### 2.1 저장소 클론

```bash
mkdir -p ~/ros2_ws/src
cd ~/ros2_ws/src
git clone -b jazzy https://github.com/ROBOTIS-GIT/DynamixelSDK.git && \
  git clone -b jazzy https://github.com/ROBOTIS-GIT/dynamixel_interfaces.git && \
  git clone -b jazzy https://github.com/ROBOTIS-GIT/dynamixel_hardware_interface.git && \
  git clone -b jazzy https://github.com/ROBOTIS-GIT/open_manipulator.git
```

### 2.2 의존성 설치

```bash
cd ~/ros2_ws
sudo rosdep init
rosdep update
rosdep install -i --from-path src --rosdistro $ROS_DISTRO \
  --skip-keys="librealsense2 dynamixel_hardware_interface dynamixel_interfaces dynamixel_sdk open_manipulator robotis_interfaces" \
  -y
```

### 2.3 빌드 & source

```bash
colcon build --symlink-install --cmake-args -DCMAKE_BUILD_TYPE=Release
source ~/ros2_ws/install/setup.bash
```

`~/.bashrc`에 추가해두면 편합니다:

```bash
echo "source /opt/ros/${ROS_DISTRO}/setup.bash" >> ~/.bashrc
echo "source ~/ros2_ws/install/setup.bash" >> ~/.bashrc
echo "alias cb='colcon build --symlink-install --cmake-args -DCMAKE_BUILD_TYPE=Release'" >> ~/.bashrc
source ~/.bashrc
```

### 2.4 udev 규칙 생성

```bash
ros2 run open_manipulator_bringup om_create_udev_rules
```

---

## 3. OpenCR 펌웨어 업로드 (Arduino IDE)

전원을 켜기 전에 이 단계를 마쳐야 합니다. **여기를 건너뛰면 ROS2 통신 시
`[TxRxResult] There is no status packet!` 오류가 발생합니다.**

### 3.1 32비트 컴파일러 (Ubuntu 24.04 대응)

매뉴얼의 `libncurses5-dev:i386`은 24.04(Noble)에서 제공되지 않습니다. 아래로 대체하세요.

```bash
sudo dpkg --add-architecture i386
sudo apt update
sudo apt install libc6:i386 libncurses6:i386 libstdc++6:i386
```

> 증상: 위 패키지 없이 업로드 시 `arm-none-eabi-g++: no such file or directory` (파일은 있는데 32비트 동적 링커가 없어서 발생).

### 3.2 Arduino IDE 설치 & 실행

```bash
# https://www.arduino.cc/en/software 에서 Linux 64bit용 zip 다운로드 후
cd ~/Downloads
unzip arduino-ide_2.3.10_Linux_64bit.zip -d ~/tools/
cd ~/tools/arduino-ide_2.3.10_Linux_64bit
./arduino-ide --no-sandbox    # sandbox 에러 회피 (SUID sandbox helper 에러 시 필수)
```

alias 등록:

```bash
echo "alias arduino-ide='~/tools/arduino-ide_2.3.10_Linux_64bit/arduino-ide --no-sandbox'" >> ~/.bashrc
source ~/.bashrc
```

### 3.3 OpenCR 보드 패키지 설치

1. USB 포트 권한 설정:
   ```bash
   wget https://raw.githubusercontent.com/ROBOTIS-GIT/OpenCR/master/99-opencr-cdc.rules
   sudo cp ./99-opencr-cdc.rules /etc/udev/rules.d/
   sudo udevadm control --reload-rules
   sudo udevadm trigger
   ```
2. Arduino IDE 실행 → `File → Preferences` → Additional Boards Manager URLs에 추가:
   ```
   https://raw.githubusercontent.com/ROBOTIS-GIT/OpenCR/master/arduino/opencr_release/package_opencr_index.json
   ```
3. OpenCR을 USB로 연결한 상태에서 포트 먼저 설정합니다.

   ![port setting 1](images/port-setting-1.png)
   ![port setting 2](images/port-setting-2.png)

4. `Tools → Board → Boards Manager`에서 `OpenCR` 검색 후 설치.

   ![boards manager search & install](images/boardsmanager-search-install.png)

5. `Tools → Board`에 OpenCR Board가 뜨는지 확인 후 선택.

   ![OpenCR board selected in list](images/board-list-opencr-selected.png)

6. modemmanager 제거 (업로드 후 재연결 시 AT 명령 충돌 방지):
   ```bash
   sudo apt-get purge modemmanager
   ```

### 3.4 usb_to_dxl 펌웨어 업로드

1. `File → Examples → OpenCR → 10.Etc → usb_to_dxl` 예제 열기
2. Upload 클릭
3. 업로드 완료 로그 확인

> 업로드 실패 시 Recovery Mode: 전원 ON → `PUSH SW2` 누른 채 `Reset` 눌렀다 떼기 → `PUSH SW2` 떼기. STATUS LED가 100ms 간격으로 깜빡이면 성공.

업로드 완료 후 전원을 켜면 모든 DYNAMIXEL LED가 한 번씩 깜빡여야 정상입니다.

---

## 4. 브링업 & 텔레오퍼레이션 (Stage 1)

> **[포트 지정 필수]** `open_manipulator_x.launch.py`의 `port_name` 기본값은 U2D2용(`/dev/ttyUSB0`)입니다. OpenCR을 쓰므로 `port_name:=/dev/ttyACM0`을 반드시 명시하세요. 누락 시 `Error opening serial port!`가 반복 발생합니다.

### 4.1 브링업

```bash
ros2 launch open_manipulator_bringup open_manipulator_x.launch.py port_name:=/dev/ttyACM0
```

이 터미널을 켜둔 채로 아래 명령을 다른 터미널에서 실행합니다 (`/joint_states` 토픽이 브링업 노드에서 나오기 때문).

### 4.2 키보드 텔레오퍼레이션

```bash
ros2 run open_manipulator_teleop open_manipulator_x_teleop
```

패키지명이 버전에 따라 다를 수 있습니다. 안 되면 `ros2 pkg list | grep teleop`으로 확인하세요.

### 4.3 GUI 조작 (선택)

```bash
# 터미널 1: 브링업 (위 4.1)
# 터미널 2:
ros2 launch open_manipulator_moveit_config open_manipulator_x_moveit.launch.py
# 터미널 3:
ros2 launch open_manipulator_gui open_manipulator_x_gui.launch.py
```

### 4.4 RViz에서 목표 자세 Plan & Execute 확인

MoveIt 플러그인 인터랙티브 마커를 드래그 → Plan → Execute로 실물 팔이 움직이는지 확인합니다. `arm`/`gripper` 두 planning group이 정상 동작해야 다음 단계로 넘어갈 수 있습니다.

![RViz MoveIt plan & execute demo](images/moveit2-rviz-demo.gif)

---

## 5. MoveIt2 Pick-and-Place (Stage 2)

**목표**: 고정된 좌표의 물체를 집어서 다른 고정된 좌표에 놓는 동작을 `moveit_py`로 스스로 경로 계획해서 수행. (카메라 인식 없음 — Stage 3 예정. 좌표는 하드코딩)

참고 매뉴얼:
- [MoveIt2 Your First Project](https://moveit.picknik.ai/main/doc/tutorials/your_first_project/your_first_project.html)
- [automaticaddison pick-and-place tutorial](https://automaticaddison.com/pick-and-place-task-using-moveit-2-and-perception-ros2-jazzy/)

### 5.1 사전 준비 (Stage 1에서 이어짐)

```bash
# 터미널 1
ros2 launch open_manipulator_bringup open_manipulator_x.launch.py port_name:=/dev/ttyACM0
# 터미널 2
ros2 launch open_manipulator_moveit_config open_manipulator_x_moveit.launch.py
```

### 5.2 아키텍처 노트: `moveit_py`는 클라이언트가 아니다

`moveit_py`의 `MoveItPy` 클래스는 `MoveItCpp`를 감싼 것으로, 이미 떠 있는 `move_group` 노드에 붙는 얇은 클라이언트(RViz가 쓰는 C++ `MoveGroupInterface` 방식)가 **아닙니다.** 스크립트 프로세스 안에 독립된 두 번째 플래닝 파이프라인이 새로 뜨는 구조입니다.

**실무적 의미**: 스크립트를 돌리는 동안 RViz의 Plan/Execute를 **동시에 쓰지 마세요.** 둘 다 같은 `arm_controller`/`gripper_controller`에 goal을 보내 충돌할 수 있습니다. 시각화 확인용으로만 RViz를 켜두는 건 괜찮습니다.

### 5.3 패키지 구조

기존 ROBOTIS 벤더 패키지(`open_manipulator/`)와 분리된 독립 패키지로 생성했습니다. 업스트림 추적 코드와 과제 코드를 섞지 않기 위함이며, Stage 3(카메라 인식) 확장을 고려한 구조입니다.

```
~/ros2_ws/src/open_manipulator_x_pick_place/   (ament_python)
├── package.xml          # depend: rclpy, moveit_py, geometry_msgs
├── setup.py
├── setup.cfg
├── resource/open_manipulator_x_pick_place
└── open_manipulator_x_pick_place/
    ├── __init__.py
    └── pick_and_place.py
```

### 5.4 코드 구조 요약

- **설정 상수**: `ARM_GROUP`/`GRIPPER_GROUP`("arm"/"gripper"), SRDF named state(`home`, `open`/`close`), `GRASP_POSITION`/`PRE_GRASP_POSITION`(좌표), `PRE_PLACE_JOINT_POSITIONS`/`PLACE_JOINT_POSITIONS`(관절값 — 이유는 troubleshooting 참고), velocity/acceleration scaling 0.2 고정.
- **`build_moveit_py()`**: `MoveItConfigsBuilder`로 기존 `open_manipulator_moveit_config` 패키지의 srdf/joint_limits/controllers/kinematics를 그대로 읽어 `MoveItPy` 인스턴스 생성.
- **`plan_and_execute()`**: 모든 이동의 공통 안전 로직 — `set_start_state_to_current_state()` → `plan()` → **실패 시 로그만 남기고 즉시 반환 (execute 호출 안 함)** → 성공 시 `execute()` → 다음 planning 전 0.5초 대기.
- **이동 방식 3가지**: `move_arm_to_named_state()` (SRDF named state), `move_arm_to_pose()` (좌표, IK는 MoveIt이 계산), `move_arm_to_joint_positions()` (관절값 직접 지정, IK 계산 생략).
- **`run_pick_and_place()` 9단계**: home → pre-grasp(좌표) → grasp(좌표) → gripper close → lift(좌표) → pre-place(관절값) → place(관절값) → gripper open → retreat+home(관절값→named state).
- **`main()`**: `rclpy.init()` → `MoveItPy` 생성 → 시퀀스 실행 → 정상 종료 대신 `os._exit()`로 강제 종료 (이유는 troubleshooting #3 참고).

### 5.5 좌표/관절값 뽑는 법 — 수동교시(hand-teaching)

RViz 드래그+Plan+Execute를 반복하는 것보다 훨씬 빠르고 정확합니다.

1. **토크 끄기** (팔이 손으로 자유롭게 움직여짐):
   ```bash
   ros2 service call /dynamixel_hardware_interface/set_dxl_torque std_srvs/srv/SetBool "{data: false}"
   ```
   ⚠️ 토크가 꺼지는 순간 팔이 자중으로 축 늘어집니다 — 호출 직전에 반드시 손으로 받치세요.
2. 원하는 위치로 손으로 옮깁니다. (`/joint_states`가 실시간으로 실제 인코더 값을 반영)
3. **좌표 읽기**:
   ```bash
   ros2 run tf2_ros tf2_echo world end_effector_link
   ```
4. **관절값 읽기**:
   ```bash
   ros2 topic echo /joint_states --once
   ```
5. **측정 끝나면 토크 다시 켜기** (필수 — 안 하면 팔이 명령에 반응 안 함):
   ```bash
   ros2 service call /dynamixel_hardware_interface/set_dxl_torque std_srvs/srv/SetBool "{data: true}"
   ```

### 5.6 실행

```bash
# 브링업이 켜져 있고 토크가 켜져 있는지 확인
source ~/ros2_ws/install/setup.bash
python3 ~/ros2_ws/src/open_manipulator_x_pick_place/open_manipulator_x_pick_place/pick_and_place.py
```

RViz/move_group은 **동시에 조작하지 마세요** (Plan/Execute 겹치면 안 됨).

### 5.7 안전 설계

- velocity/acceleration scaling factor 기본 0.2로 낮게 고정
- 매 스텝 `plan()` 결과를 확인, **실패 시 execute() 호출 없이 시퀀스 즉시 중단**
- 각 waypoint 진입/완료 시 로그 출력 (`[N. 스텝이름] planning...` → `done.` 또는 `FAILED`)
- 4축 팔 IK 실패(`Unable to sample any valid states`)도 에러로 감지되어 안전하게 정지

에러가 나면 [troubleshooting.md](./troubleshooting.md)를 확인하세요.

---

## 6. 데모 영상

| 단계 | 영상 |
| --- | --- |
| Stage 1 — 브링업 & 텔레오퍼레이션 | [Google Drive](https://drive.google.com/file/d/1K93JUZuvyp8dnuQPijcDIxUjZTn1F5Je/view?usp=drive_link) |
| Stage 2(1) — RViz MoveIt Plan/Execute | [Google Drive](https://drive.google.com/file/d/18vKE2qVjf_8h33P4QQ6-17PfcHR_aTVI/view?usp=drive_link) (gif: [images/moveit2-rviz-demo.gif](images/moveit2-rviz-demo.gif)) |
| Stage 2(2) — MoveIt2 Pick-and-Place 전체 시퀀스 | [Google Drive #1](https://drive.google.com/file/d/1Uw4575PrhzrfrSFwYhEzHdP2zxn7AYYV/view?usp=drive_link) · [Google Drive #2](https://drive.google.com/file/d/1qtRa02dMAlS_XRpRkwHJCXmmofkJri9O/view?usp=drive_link) |

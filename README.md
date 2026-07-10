# OpenManipulator-X · 텔레오퍼레이션 → MoveIt2 자율 Pick-and-Place

로봇팔 하나를 손으로 움직이는 데서 시작해, 목표 좌표만 주면 스스로 경로를 짜서 집고 놓는 데까지의 과정을 담은 저장소입니다. DGIST CSI Lab 인턴 프로젝트 "MoveIt2gather"의 Stage 1~2 결과물입니다.

## 진행 상태

- [x] **Stage 1** — 텔레오퍼레이션: 브링업, 키보드 텔레옵, GUI 조작
- [x] **Stage 2** — MoveIt2 자율 Pick-and-Place (`moveit_py`, 하드코딩 좌표)
- [ ] Stage 3 — 카메라 기반 물체 인식
- [ ] Stage 4 — Jetson 온보드 VLA 추론
- [ ] Stage 5 — 다중 암 협업

## 스택

| 구분 | 내용 |
| --- | --- |
| OS | Ubuntu 24.04 LTS |
| 미들웨어 | ROS 2 Jazzy Jalisco |
| 모션 플래닝 | MoveIt 2 (`moveit_py`) |
| 하드웨어 | OpenManipulator-X (4축) + OpenCR 제어보드 |
| 언어 | Python 3.12 |

## 저장소 구조

```
ros2_ws/src/
├── (ROBOTIS 벤더 패키지: DynamixelSDK, dynamixel_interfaces,
│    dynamixel_hardware_interface, open_manipulator)
└── open_manipulator_x_pick_place/   # Stage 2 자체 구현 패키지
    └── open_manipulator_x_pick_place/
        └── pick_and_place.py
docs/
├── guidebook.md          # 재현 가이드북 (설치 ~ pick-and-place)
├── troubleshooting.md    # 에러/원인/해결 모음
└── images/
```

## Quick Start

```bash
# 1. 브링업 (OpenCR, 포트 명시 필수)
ros2 launch open_manipulator_bringup open_manipulator_x.launch.py port_name:=/dev/ttyACM0

# 2. (선택) MoveIt2 RViz 플러그인으로 수동 확인
ros2 launch open_manipulator_moveit_config open_manipulator_x_moveit.launch.py

# 3. Pick-and-place 자동 실행
python3 ~/ros2_ws/src/open_manipulator_x_pick_place/open_manipulator_x_pick_place/pick_and_place.py
```

> 처음 설치하는 경우 → [docs/guidebook.md](docs/guidebook.md)를 처음부터 따라가세요. 펌웨어 업로드, 포트 권한, 32비트 라이브러리 등 하드웨어 설정이 포함되어 있습니다.
> 에러가 나면 → [docs/troubleshooting.md](docs/troubleshooting.md)에서 증상을 검색하세요.

## 데모

![RViz MoveIt Plan & Execute](docs/images/moveit2-rviz-demo.gif)

| 단계 | 영상 |
| --- | --- |
| Stage 1 — 브링업 & 텔레오퍼레이션 | [Google Drive](https://drive.google.com/file/d/1K93JUZuvyp8dnuQPijcDIxUjZTn1F5Je/view?usp=drive_link) |
| Stage 2(1) — RViz MoveIt Plan/Execute | [Google Drive](https://drive.google.com/file/d/18vKE2qVjf_8h33P4QQ6-17PfcHR_aTVI/view?usp=drive_link) |
| Stage 2(2) — Pick-and-Place 전체 시퀀스 | [Google Drive #1](https://drive.google.com/file/d/1Uw4575PrhzrfrSFwYhEzHdP2zxn7AYYV/view?usp=drive_link) · [Google Drive #2](https://drive.google.com/file/d/1qtRa02dMAlS_XRpRkwHJCXmmofkJri9O/view?usp=drive_link) |

## 문서

- [재현 가이드북](docs/guidebook.md) — 1순위 산출물. 누가 따라 해도 설치부터 pick-and-place까지 재현 가능.
- [트러블슈팅](docs/troubleshooting.md) — 실제로 겪은 에러와 해결법.

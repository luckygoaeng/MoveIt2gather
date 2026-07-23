# OpenManipulator-X · 텔레오퍼레이션 → MoveIt2 자율 Pick-and-Place → 젯슨 온보드 VLA

로봇팔 하나를 손으로 움직이는 데서 시작해, 목표 좌표만 주면 스스로 경로를 짜서 집고 놓고, 나아가 젯슨 오린 나노 단독으로 VLA(비전-언어-액션) 모델을 온보드 추론까지 돌리는 과정을 담은 저장소입니다. DGIST CSI Lab 인턴 프로젝트 "MoveIt2gather"의 Stage 1~4 결과물입니다.

## 진행 상태

- [x] **Stage 1** — 텔레오퍼레이션: 브링업, 키보드 텔레옵, GUI 조작
- [x] **Stage 2** — MoveIt2 자율 Pick-and-Place (`moveit_py`, 하드코딩 좌표)
- [x] **Stage 3** — 세션별 자동 카메라-로봇 캘리브레이션 + ArUco 마커 기반 Pick-and-Place
- [x] **Stage 4** — 젯슨 오린 나노 단독 온보드: ROS 2 워크스페이스 전체 재빌드 + VLA 모델(SmolVLA) 제로샷 온보드 추론
  - 온보드 실행·제어 루프 Hz 실측 완료 (~10Hz). 제로샷 cross-embodiment 한계로 실제 pick 성공은 못함 (예상된 결과, 관절4/손목 급반전 패턴 재현)
  - SmolVLA 내부 VLM(SmolVLM2)만 단독 추출해 미세조정 없는 신규 물체 인식 여부 추가 검증 — 대략적 존재 인식은 성공, 정밀 그리드/좌표 응답은 신뢰 불가(9지선다 강제 시 답변 붕괴 현상 발견)
- [ ] Stage 5 — 다중 암 협업

## 스택

| 구분 | 내용 |
| --- | --- |
| OS | Ubuntu 24.04 LTS |
| 미들웨어 | ROS 2 Jazzy Jalisco |
| 모션 플래닝 | MoveIt 2 (`moveit_py`) |
| 하드웨어 | OpenManipulator-X (4축) + OpenCR 제어보드, Jetson Orin Nano Developer Kit (Stage 4 온보드) |
| 카메라/인식 | Logitech C920 (USB 웹캠) + `ros2-aruco-pose-estimation` (ArUco, monocular solvePnP) |
| VLA (Stage 4) | `lerobot`(0.4.4) + `lerobot-ros` + SmolVLA(`lerobot/smolvla_base`), 내부 VLM은 `HuggingFaceTB/SmolVLM2-500M-Video-Instruct` — conda 환경(`vla`, python 3.12)에서 시스템 ROS 2와 분리 실행, `torch==2.13.0+cu132`(GPU) |
| 언어 | Python 3.12 |

## 저장소 구조

```
ros2_ws/src/
├── (ROBOTIS 벤더 패키지: DynamixelSDK, dynamixel_interfaces,
│    dynamixel_hardware_interface, open_manipulator)
├── ros2-aruco-pose-estimation/       # ArUco 마커 인식 (Stage 3)
└── open_manipulator_x_pick_place/    # 자체 구현 패키지
    └── open_manipulator_x_pick_place/
        ├── pick_and_place.py             # Stage 2, 하드코딩 좌표
        ├── calibrate_camera_to_base.py   # Stage 3 — 세션별 자동 캘리브레이션
        └── pick_and_place_aruco.py       # Stage 3 — ArUco 마커 기반 pick-and-place
ros2_ws/vla/                          # Stage 4, ament 패키지 아님 (순수 pip, conda 환경 전용)
├── lerobot-ros/                          # ycheng517/lerobot-ros 클론 (ROS2Robot/ROS2Config)
└── lerobot_robot_open_manipulator_x/     # 우리 로봇 전용 서브클래스 (src 레이아웃)
docs/
├── guidebook.md          # 재현 가이드북 (설치 ~ Stage 4 VLA 온보드 추론)
├── troubleshooting.md    # 에러/원인/해결 모음
└── images/
```

## Quick Start

```bash
# 1. 브링업 (OpenCR, 포트 명시 필수)
ros2 launch open_manipulator_bringup open_manipulator_x.launch.py port_name:=/dev/ttyACM0

# 2. (선택) MoveIt2 RViz 플러그인으로 수동 확인
ros2 launch open_manipulator_moveit_config open_manipulator_x_moveit.launch.py

# 3. Pick-and-place 자동 실행 (Stage 2, 하드코딩 좌표)
python3 ~/ros2_ws/src/open_manipulator_x_pick_place/open_manipulator_x_pick_place/pick_and_place.py
```

> 처음 설치하는 경우 → [docs/guidebook.md](docs/guidebook.md)를 처음부터 따라가세요. 펌웨어 업로드, 포트 권한, 32비트 라이브러리 등 하드웨어 설정이 포함되어 있습니다.
> 에러가 나면 → [docs/troubleshooting.md](docs/troubleshooting.md)에서 증상을 검색하세요.
> Stage 3(카메라-로봇 자동 캘리브레이션 + ArUco pick-and-place)는 카메라·ArUco 인식 노드까지 포함해 터미널 5개를 순서대로 띄워야 해서 [guidebook.md 6.6절](docs/guidebook.md#66-실행-순서-매-테스트-세션마다)을 참고하세요.
> Stage 4(젯슨 온보드 VLA)는 conda 환경 구축부터 필요해 Quick Start로 요약하기 어렵습니다 — [guidebook.md 8.9절](docs/guidebook.md#89-stage-4-본편--vla-모델smolvla-온보드-제로샷-추론)부터 순서대로 따라가세요.

## 데모

![RViz MoveIt Plan & Execute](docs/images/moveit2-rviz-demo.gif)

| 단계 | 영상 |
| --- | --- |
| Stage 1 — 브링업 & 텔레오퍼레이션 | [Google Drive](https://drive.google.com/file/d/1K93JUZuvyp8dnuQPijcDIxUjZTn1F5Je/view?usp=drive_link) |
| Stage 2(1) — RViz MoveIt Plan/Execute | [Google Drive](https://drive.google.com/file/d/18vKE2qVjf_8h33P4QQ6-17PfcHR_aTVI/view?usp=drive_link) |
| Stage 2(2) — Pick-and-Place 전체 시퀀스 | [Google Drive #1](https://drive.google.com/file/d/1Uw4575PrhzrfrSFwYhEzHdP2zxn7AYYV/view?usp=drive_link) · [Google Drive #2](https://drive.google.com/file/d/1qtRa02dMAlS_XRpRkwHJCXmmofkJri9O/view?usp=drive_link) |
| Stage 3(1) — 자동 캘리브레이션 | [Google Drive](https://drive.google.com/file/d/17QxlfDrqPBBf16Jz6fXvbErETiMCa5CH/view?usp=drive_link) |
| Stage 3(2) — ArUco Pick-and-Place 전체 데모 | [Google Drive](https://drive.google.com/file/d/1U9aCBM_tTKyhq0AbYvM_-bDeTZBCH7t3/view?usp=drive_link) |
| Stage 4 — 젯슨 온보드 캠 화면 (동작 확인용) | [Google Drive](https://drive.google.com/file/d/1U1JNCLtqICSsCwSccz-v2LYSHA6AVwgt/view?usp=drive_link) |
| Stage 4 — 젯슨 온보드 Pick-and-Place 데모 (동작 확인용) | [Google Drive](https://drive.google.com/file/d/1XUJyIx5i2XMnKBULv_raDz_S70OY8UFj/view?usp=drive_link) |
| Stage 4 본편 — SmolVLA 제로샷 실행 run2 | [Google Drive](https://drive.google.com/file/d/1BOmTG8LVB3XfCFSMgp6zzKnyyDFrbAaY/view?usp=drive_link) |
| Stage 4 본편 — SmolVLA 제로샷 실행 run3 | [Google Drive](https://drive.google.com/file/d/17zq8thvSAxRO6rvzL3pNFxW-ZbJuWXnX/view?usp=drive_link) |

## 문서

- [재현 가이드북](docs/guidebook.md) — 1순위 산출물. 누가 따라 해도 설치부터 pick-and-place까지 재현 가능.
- [트러블슈팅](docs/troubleshooting.md) — 실제로 겪은 에러와 해결법.

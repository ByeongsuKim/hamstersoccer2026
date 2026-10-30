# ⚽ 햄스터봇 AI 로봇축구 (HamsterSoccer 2026)

천장 카메라로 경기장을 보면서 햄스터봇 2대가 노란 공을 몰고 사람과 축구 경기를 하는 Windows 프로그램입니다.
로봇의 움직임은 프로그램이 직접 계산하고, **Claude 감독**(선택 기능)이 경기 상황을 보고 몇 초마다 전략을 고릅니다.

## 설치

1. [Releases](https://github.com/ByeongsuKim/hamstersoccer2026/releases) 에서 `HamsterSoccer-Setup-<버전>.exe` 를 내려받아 실행합니다.
2. **Claude API 키** 화면에서 Anthropic API 키(`sk-ant-...`)를 입력합니다. 비워 두면 나중에 앱의 **[API 키]** 로 입력할 수 있습니다.
   키는 `%APPDATA%\HamsterSoccer\config.json` 에 저장되며, 프로그램을 제거하면 함께 지워집니다.
3. 햄스터봇 USB 동글용 **Silicon Labs CP210x 드라이버**는 설치 파일에 들어 있지 않습니다.
   Silicon Labs 공식 사이트(<https://www.silabs.com/developer-tools/usb-to-uart-bridge-vcp-drivers>)에서 받아 따로 설치하세요.
   설치되면 장치 관리자의 "포트(COM & LPT)" 에 동글마다 "Silicon Labs CP210x USB to UART Bridge (COMx)" 가 보입니다.

여러 PC 에 한꺼번에 설치할 때:
```bat
HamsterSoccer-Setup-1.0.0.exe /VERYSILENT /TASKS="desktopicon" /APIKEY=sk-ant-...
```

> 설치 직후 첫 실행은 백신(V3 등) 검사 때문에 30초~1분 정도 걸리거나 한두 번 실패할 수 있습니다. 잠시 뒤 다시 실행하세요.
> Windows SmartScreen 경고가 나오면 **추가 정보 → 실행** 을 누르세요 (코드 서명이 없는 프로그램이라 표시됩니다).

**필요한 것**: Windows 10/11 64비트, 햄스터봇 2대 + USB 동글 2개, ArUco 마커(ID 0, 1)를 붙인 로봇,
노란 공, 천장 IP 카메라(`192.168.66.1:9527`, PC 를 카메라 와이파이에 연결).

## 사용법

1. 상단 **연결 / 인식 상태** 가 모두 초록색인지 확인합니다 (카메라, 공, 로봇 1·2).
2. **AI골대**(화면 왼쪽)와 **P골대**(화면 오른쪽)를 눌러 영상 위에서 골대 영역을 드래그합니다.
3. AI 전략을 고르고 **시작** 을 누릅니다. 영상 위 남색 줄에 현재 전략과 로봇별 역할이 표시됩니다.

| 전략 | 동작 |
|---|---|
| 1. 두 대 모두 공격 | 공에 가까운 로봇이 몰고 가고, 다른 로봇은 옆에서 받쳐줌 |
| 2. 1대 공격 + 1대 수비 | 로봇 1 은 공격, 로봇 2 는 골키퍼 |
| 3. 가까우면 몰고가기 / 멀면 수비 | 공에 가까운 로봇이 몰고 가다가, 공이 멀어지면 수비로 복귀 |

- **골인**: 노란 공 **전체**가 골대 영역 안에 들어가야 인정됩니다. 골인하면 로봇들이 3초간 춤을 춥니다.
- **🧠 Claude 감독**: 켜면 경기 중 정해진 주기(기본 5초)마다 점수·시간·공과 로봇 위치를 Claude 에게 보내 전략을 고르게 합니다.
  모델은 **Haiku 5.5 (가장 저렴, 기본)** / Sonnet 5.5 / Opus 5.5 중에서 고를 수 있고, 누적 호출 수와 비용이 표시됩니다.
- **안전**: 카메라 영상이 끊기거나 로봇이 화면에서 사라지면 해당 로봇을 즉시 멈춥니다. **정지** 를 누르면 모든 로봇이 멈춥니다.

## 소스에서 실행·빌드

```bat
pip install -r requirements.txt
python HamsterbotSoccer.py          :: 바로 실행
build.bat                           :: 실행 파일 → dist\HamsterSoccer\
build_installer.bat                 :: 설치 파일 → installer\Output\HamsterSoccer-Setup-<버전>.exe
```

설치 파일을 만들려면 Inno Setup 6 이 필요합니다: `winget install -e --id JRSoftware.InnoSetup --scope user`

버전을 올릴 때는 `HamsterbotSoccer.py` 의 `APP_VERSION` 과 `installer/HamsterSoccer.iss` 의 `MyAppVersion` 을 함께 바꿉니다.

| 파일 | 내용 |
|---|---|
| `HamsterbotSoccer.py` | 화면, 카메라·공·마커 인식, 골 판정, 세리머니, 로봇 제어 |
| `soccer_ai.py` | 전략 1~3: 역할 분담과 로봇별 목표 지점 계산 |
| `claude_coach.py` | Claude 감독: 경기 상황을 보내고 전략을 받아옴 (별도 스레드) |
| `HamsterSoccer.spec` | PyInstaller 빌드 설정 |
| `installer/HamsterSoccer.iss` | 설치 파일 스크립트 (API 키 입력) |

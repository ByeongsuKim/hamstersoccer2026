# ⚽ 햄스터봇 AI 로봇축구 (HamsterSoccer 2026)

천장 카메라로 경기장을 보면서 햄스터봇 2대가 노란 공을 몰고 사람과 축구 경기를 하는 Windows 프로그램입니다.
로봇의 움직임은 프로그램이 직접 계산하며, **인터넷 없이** 동작합니다.

> v1.0.5 부터 Claude 감독(인터넷으로 Claude API 를 불러 전략을 고르는 기능)을 뺐습니다.
> 전략은 화면에서 직접 고릅니다. 감독 기능이 있는 버전은 v1.0.3 Release 를 참고하세요.

## 설치

1. [Releases](https://github.com/ByeongsuKim/hamstersoccer2026/releases) 에서 `HamsterSoccer-Setup-<버전>.exe` 를 내려받아 실행합니다.
2. 햄스터봇 USB 동글용 **Silicon Labs CP210x 드라이버**는 설치 파일에 들어 있지 않습니다.
   Silicon Labs 공식 사이트(<https://www.silabs.com/developer-tools/usb-to-uart-bridge-vcp-drivers>)에서 받아 따로 설치하세요.
   설치되면 장치 관리자의 "포트(COM & LPT)" 에 동글마다 "Silicon Labs CP210x USB to UART Bridge (COMx)" 가 보입니다.

여러 PC 에 한꺼번에 설치할 때:
```bat
HamsterSoccer-Setup-1.0.5.exe /VERYSILENT /TASKS="desktopicon"
```

> 설치 직후 첫 실행은 백신(V3 등) 검사 때문에 30초~1분 정도 걸리거나 한두 번 실패할 수 있습니다. 잠시 뒤 다시 실행하세요.
> Windows SmartScreen 경고가 나오면 **추가 정보 → 실행** 을 누르세요 (코드 서명이 없는 프로그램이라 표시됩니다).

**필요한 것**: Windows 10/11 64비트, 햄스터봇 2대 + USB 동글 2개, ArUco 마커(ID 0, 1)를 붙인 로봇,
노란 공, 천장 IP 카메라(PC 를 카메라 와이파이에 연결) 또는 USB 카메라.

## 사용법

1. **프로그램을 켜기 전에** 햄스터봇 USB 동글 2개를 꽂고 로봇 전원을 켭니다 (프로그램은 시작할 때 동글을 찾습니다).
2. 상단 **연결 / 인식 상태** 가 모두 초록색인지 확인합니다 (카메라, 공, 로봇 1·2).
   카메라가 안 나오면 **[카메라 선택 / 연결]** 을 누르세요. 같은 네트워크의 IP 카메라(포트 9527)와 PC 에 꽂힌
   USB 카메라를 자동으로 찾아 미리보기와 함께 보여 줍니다. 노트북이 바뀌어 카메라 IP 가 달라져도 여기서 고르면 됩니다.
   고른 카메라는 저장되어 다음 실행 때도 그대로 쓰입니다.
3. **AI골대**(화면 왼쪽)와 **P골대**(화면 오른쪽)를 눌러 영상 위에서 골대 영역을 드래그합니다.
4. AI 전략을 고르고 **시작** 을 누릅니다. 영상 위 남색 줄에 현재 전략과 로봇별 역할이 표시됩니다.

| 전략 | 동작 |
|---|---|
| 1. 두 대 모두 공격 | 공에 가까운 로봇이 몰고 가고, 다른 로봇은 옆에서 받쳐줌 |
| 2. 1대 공격 + 1대 수비 | 로봇 1 은 공격, 로봇 2 는 골키퍼 |
| 3. 가까우면 몰고가기 / 멀면 수비 | 공에 가까운 로봇이 몰고 가다가, 공이 멀어지면 수비로 복귀 |

- **골인**: 노란 공 **전체**가 골대 영역 안에 들어가야 인정됩니다. 로봇은 공을 골대 안쪽 깊숙이 밀어 넣고, 골인하면 3초간 춤을 춥니다.
- **안전**: 카메라 영상이 0.5초 넘게 끊기거나 로봇이 화면에서 사라지면 해당 로봇을 즉시 멈춥니다. **정지** 를 누르면 모든 로봇이 멈춥니다.

## 소스(py)로 실행하기

1. **Python 3.10 이상**을 설치합니다 (<https://www.python.org>, 설치 화면에서 **"Add python.exe to PATH"** 체크).
2. 이 저장소를 받아서 **`setup.bat`** 을 실행합니다 (필요한 라이브러리 설치, 처음 한 번, 인터넷 필요).
3. **CP210x 드라이버**를 설치하고, **햄스터봇 USB 동글 2개를 꽂고 로봇 전원을 켭니다.**
4. PC 를 카메라 와이파이에 연결합니다 (또는 USB 카메라를 꽂습니다).
5. **`run.bat`** 으로 실행합니다. 상단 **[연결/하드웨어 점검]** 을 눌러 두 로봇의 부저가 울리면 연결된 것입니다.

설치판(exe)에서 문제가 생기면 `%APPDATA%\HamsterSoccer\app.log` 에서 로봇 연결 메시지를 확인할 수 있습니다.

## 빌드

```bat
build.bat                           :: 실행 파일 → dist\HamsterSoccer\
build_installer.bat                 :: 설치 파일 → installer\Output\HamsterSoccer-Setup-<버전>.exe
```

설치 파일을 만들려면 Inno Setup 6 이 필요합니다: `winget install -e --id JRSoftware.InnoSetup --scope user`

버전을 올릴 때는 `HamsterbotSoccer.py` 의 `APP_VERSION` 과 `installer/HamsterSoccer.iss` 의 `MyAppVersion` 을 함께 바꿉니다.

| 파일 | 내용 |
|---|---|
| `HamsterbotSoccer.py` | 화면, 카메라·공·마커 인식, 골 판정, 세리머니, 로봇 제어 |
| `soccer_ai.py` | 전략 1~3: 역할 분담과 로봇별 목표 지점 계산 |
| `camera_discovery.py` | 카메라 자동 탐색 (IP 카메라·USB 카메라 후보와 미리보기) |
| `HamsterSoccer.spec` | PyInstaller 빌드 설정 |
| `installer/HamsterSoccer.iss` | 설치 파일 스크립트 |

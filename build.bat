@echo off
rem 햄스터봇 AI 로봇축구 앱을 Windows 실행 파일로 만듭니다. 결과: dist\HamsterSoccer\HamsterSoccer.exe
rem 빌드 설정은 HamsterSoccer.spec 에 있습니다 (코드 묶음을 exe 밖 .pkg 로 분리, 불필요한 라이브러리 제외).
cd /d "%~dp0"
python -m pip install -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm --clean HamsterSoccer.spec
if errorlevel 1 (
  echo 빌드 실패
  pause
  exit /b 1
)
echo 완료: dist\HamsterSoccer\HamsterSoccer.exe

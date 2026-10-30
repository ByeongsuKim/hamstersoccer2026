@echo off
rem 소스(py)로 실행하기 위한 라이브러리 설치 (처음 한 번, 인터넷 필요)
cd /d "%~dp0"
python --version || (
  echo Python 이 없습니다. https://www.python.org 에서 설치하세요 ^(설치 화면에서 "Add python.exe to PATH" 체크^).
  pause
  exit /b 1
)
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
echo.
echo 설치 완료. run.bat 으로 실행하세요.
pause

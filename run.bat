@echo off
chcp 65001 >nul
rem 소스(py)로 햄스터봇 AI 로봇축구 실행. 처음 한 번은 setup.bat 으로 필요한 라이브러리를 설치하세요.
rem 실행 전에 햄스터봇 USB 동글 2개를 꽂고 로봇 전원을 켜 두어야 연결됩니다.
cd /d "%~dp0"
python HamsterbotSoccer.py
if errorlevel 1 pause

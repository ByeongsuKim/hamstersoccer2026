@echo off
rem 실행 파일을 빌드한 뒤 설치 파일을 만듭니다. 결과: installer\Output\HamsterSoccer-Setup-<버전>.exe
rem Inno Setup 6 필요: winget install -e --id JRSoftware.InnoSetup --scope user
cd /d "%~dp0"
call build.bat || exit /b 1

set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
  echo Inno Setup 6 을 찾을 수 없습니다.
  pause
  exit /b 1
)
"%ISCC%" installer\HamsterSoccer.iss || (pause & exit /b 1)
echo 완료: installer\Output

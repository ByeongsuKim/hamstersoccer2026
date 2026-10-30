; 햄스터봇 AI 로봇축구 설치 파일 (Inno Setup 6)
; 먼저 build.bat 으로 dist\HamsterSoccer 를 만든 뒤 build_installer.bat 으로 컴파일합니다.

#define MyAppName "햄스터봇 AI 로봇축구"
#define MyAppVersion "1.0.5"
#define MyAppPublisher "ByeongsuKim"
#define MyAppExeName "HamsterSoccer.exe"

[Setup]
AppId={{9D2C5A71-3E8B-4F06-B1D4-7A6E2C9F0B35}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
; 관리자 권한 없이 사용자 계정에 설치 (관리자라면 '모든 사용자' 설치도 선택 가능)
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\HamsterSoccer
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile=..\assets\app.ico
OutputDir=Output
OutputBaseFilename=HamsterSoccer-Setup-{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\HamsterSoccer\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 프로그램을 지우면 설정(고른 카메라 등)과 실행 로그도 함께 지운다
Type: filesandordirs; Name: "{userappdata}\HamsterSoccer"

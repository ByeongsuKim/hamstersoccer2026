; 햄스터봇 AI 로봇축구 설치 파일 (Inno Setup 6)
; 먼저 build.bat 으로 dist\HamsterSoccer 를 만든 뒤 build_installer.bat 으로 컴파일합니다.
; 설치 중 Claude API 키를 입력받아 %APPDATA%\HamsterSoccer\config.json 에 저장합니다 (앱이 읽음).

#define MyAppName "햄스터봇 AI 로봇축구"
#define MyAppVersion "1.0.2"
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
; 프로그램을 지우면 저장된 API 키와 설정도 함께 지운다
Type: filesandordirs; Name: "{userappdata}\HamsterSoccer"

[Code]
var
  KeyPage: TInputQueryWizardPage;

procedure InitializeWizard;
begin
  KeyPage := CreateInputQueryPage(wpSelectTasks,
    'Claude API 키',
    'Claude 감독 기능(AI가 경기 전략을 고르는 기능)에 쓸 Anthropic API 키를 입력하세요.',
    'API 키는 https://console.anthropic.com 에서 만들 수 있으며 sk-ant- 로 시작합니다.' + #13#10 +
    '이 PC의 사용자 설정 폴더(%APPDATA%\HamsterSoccer)에 저장되고, 프로그램을 제거하면 함께 지워집니다.' + #13#10 +
    '비워 두면 지금 저장된 키를 그대로 쓰며, 나중에 앱의 [API 키] 버튼으로 입력할 수도 있습니다.');
  KeyPage.Add('API 키:', True);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Key: String;
begin
  Result := True;
  if CurPageID = KeyPage.ID then
  begin
    Key := Trim(KeyPage.Values[0]);
    if (Key <> '') and (Pos('sk-ant-', Key) <> 1) then
      Result := MsgBox('입력한 값이 Anthropic API 키 형식(sk-ant-...)이 아닌 것 같습니다.' + #13#10 +
                       '그대로 계속할까요?', mbConfirmation, MB_YESNO) = IDYES;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Dir, Key: String;
begin
  if CurStep = ssPostInstall then
  begin
    Key := Trim(KeyPage.Values[0]);
    // 여러 PC에 조용히 설치할 때: setup.exe /VERYSILENT /APIKEY=sk-ant-...
    if Key = '' then Key := Trim(ExpandConstant('{param:APIKEY|}'));
    if Key <> '' then
    begin
      StringChangeEx(Key, '\', '\\', True);
      StringChangeEx(Key, '"', '\"', True);
      Dir := ExpandConstant('{userappdata}\HamsterSoccer');
      ForceDirectories(Dir);
      SaveStringToFile(Dir + '\config.json', '{"api_key": "' + Key + '"}', False);
    end;
  end;
end;

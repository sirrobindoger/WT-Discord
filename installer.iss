#define MyAppName "War Thunder RPC"
#define MyAppVersion "1.1.0"
#define MyAppPublisher "WarThunderRPC"
#define MyAppExeName "WarThunderRPC.exe"
#define MyOutputName "WarThunderRPC_Installer"

[Setup]
AppId={{D6D70C3A-02DB-4BCE-B79D-6500044FC746}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\WarThunderRPC
DefaultGroupName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
OutputDir=dist
OutputBaseFilename={#MyOutputName}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
DisableProgramGroupPage=yes
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "dist\WarThunderRPC.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--local"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--local"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[UninstallRun]
Filename: "{app}\{#MyAppExeName}"; Parameters: "--uninstall-service"; Flags: runhidden waituntilterminated skipifdoesntexist

[Code]
var
  IntroPage: TWizardPage;
  UsernamePage: TInputQueryWizardPage;
  SummaryPage: TWizardPage;
  SummaryLabel: TNewStaticText;
  InstallStatusText: String;

function QuoteForParam(const Value: String): String;
begin
  Result := AddQuotes(Value);
end;

function RuntimeExePath(const BaseDir: String): String;
begin
  Result := BaseDir + '\{#MyAppExeName}';
end;

function RunRuntime(const WorkDir, Params: String; var ResultCode: Integer): Boolean;
begin
  Result := Exec(RuntimeExePath(WorkDir), Params, WorkDir, SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

function EnsureUsernameConfigured(): Boolean;
begin
  Result := Trim(UsernamePage.Values[0]) <> '';
  if not Result then
    MsgBox(
      'Enter your War Thunder username. This is used for kill tracking so the RPC can attribute your match kills to the correct player.',
      mbError,
      MB_OK
    );
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = UsernamePage.ID then
    Result := EnsureUsernameConfigured();
end;

procedure InitializeWizard;
var
  IntroText: TNewStaticText;
  UsernameNote: TNewStaticText;
begin
  IntroPage := CreateCustomPage(
    wpWelcome,
    'Why administrator access is required',
    'War Thunder RPC installs a Windows service and a scheduled task.'
  );

  IntroText := TNewStaticText.Create(IntroPage);
  IntroText.Parent := IntroPage.Surface;
  IntroText.Left := 0;
  IntroText.Top := 0;
  IntroText.Width := IntroPage.SurfaceWidth;
  IntroText.Height := ScaleY(90);
  IntroText.WordWrap := True;
  IntroText.Caption :=
    'This installer will request administrator access because it installs a background Windows service and a logon task.' + #13#10#13#10 +
    'Your War Thunder username is stored per Windows user and is only used so kill tracking can identify your account correctly.' + #13#10#13#10 +
    'After install, you can start War Thunder and Discord normally.';

  UsernamePage := CreateInputQueryPage(
    IntroPage.ID,
    'War Thunder username',
    'Configure kill tracking',
    'Enter the War Thunder username that should be used for kill tracking.'
  );
  UsernamePage.Add('War Thunder username:', False);

  UsernameNote := TNewStaticText.Create(UsernamePage);
  UsernameNote.Parent := UsernamePage.Surface;
  UsernameNote.Left := 0;
  UsernameNote.Top := ScaleY(62);
  UsernameNote.Width := UsernamePage.SurfaceWidth;
  UsernameNote.Height := ScaleY(56);
  UsernameNote.WordWrap := True;
  UsernameNote.Caption :=
    'This value is used to match in-game kill feed messages to your account. ' +
    'You can change it later by running the installed app.';

  SummaryPage := CreateCustomPage(
    wpFinished,
    'Installation summary',
    'Service and worker status'
  );

  SummaryLabel := TNewStaticText.Create(SummaryPage);
  SummaryLabel.Parent := SummaryPage.Surface;
  SummaryLabel.Left := 0;
  SummaryLabel.Top := 0;
  SummaryLabel.Width := SummaryPage.SurfaceWidth;
  SummaryLabel.Height := ScaleY(120);
  SummaryLabel.WordWrap := True;
  SummaryLabel.Caption := 'War Thunder RPC is ready to install.';
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Result := '';
  InstallStatusText := '';

  if FileExists(RuntimeExePath(ExpandConstant('{app}'))) then
  begin
    if not RunRuntime(ExpandConstant('{app}'), '--uninstall-service', ResultCode) then
      Result := 'Unable to prepare the previous installation for update.'
    else if ResultCode <> 0 then
      Result := 'Unable to stop and remove the previous service before updating.';
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  UsernameParam: String;
  InstallParam: String;
begin
  if CurStep <> ssPostInstall then
    exit;

  UsernameParam := '--set-username ' + QuoteForParam(Trim(UsernamePage.Values[0]));
  if not RunRuntime(ExpandConstant('{app}'), UsernameParam, ResultCode) or (ResultCode <> 0) then
    RaiseException('The installer could not save the War Thunder username for kill tracking.');

  InstallParam :=
    '--install-service --runtime-path ' + QuoteForParam(RuntimeExePath(ExpandConstant('{app}')));
  if not RunRuntime(ExpandConstant('{app}'), InstallParam, ResultCode) or (ResultCode <> 0) then
    RaiseException('The installer could not install or start the Windows service.');

  InstallStatusText :=
    'Install location: ' + ExpandConstant('{app}') + #13#10 +
    'Tracked username: ' + Trim(UsernamePage.Values[0]) + #13#10 +
    'Service: installed and started' + #13#10 +
    'Worker task: created and launched' + #13#10#13#10 +
    'You can now start War Thunder and Discord normally.';
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = SummaryPage.ID then
  begin
    if InstallStatusText = '' then
      SummaryLabel.Caption :=
        'War Thunder RPC is installed. If you update or uninstall later, Windows will prompt for administrator access again.'
    else
      SummaryLabel.Caption := InstallStatusText;
  end;
end;

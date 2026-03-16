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
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--controller"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--controller"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[UninstallRun]
Filename: "{app}\{#MyAppExeName}"; Parameters: "--disable-controller-autostart"; Flags: runhidden waituntilterminated skipifdoesntexist
Filename: "{app}\{#MyAppExeName}"; Parameters: "--uninstall-service"; Flags: runhidden waituntilterminated skipifdoesntexist

[Code]
var
  IntroPage: TWizardPage;
  UsernamePage: TInputQueryWizardPage;
  SummaryPage: TWizardPage;
  SummaryLabel: TNewStaticText;
  InstallStatusText: String;
  InstallWarnings: String;

function QuoteForParam(const Value: String): String;
begin
  Result := AddQuotes(Value);
end;

function RuntimeExePath(const BaseDir: String): String;
begin
  Result := BaseDir + '\{#MyAppExeName}';
end;

function InstallerLogDir(): String;
begin
  Result := ExpandConstant('{commonappdata}\WarThunderRPC');
end;

function InstallerLogPath(): String;
begin
  Result := InstallerLogDir() + '\installer.log';
end;

procedure AppendInstallerLog(const Message: String);
begin
  ForceDirectories(InstallerLogDir());
  SaveStringToFile(
    InstallerLogPath(),
    GetDateTimeString('yyyy-mm-dd hh:nn:ss', #0, #0) + ' ' + Message + #13#10,
    True
  );
end;

procedure AddInstallWarning(const Message: String);
begin
  if InstallWarnings <> '' then
    InstallWarnings := InstallWarnings + #13#10;
  InstallWarnings := InstallWarnings + '- ' + Message;
  AppendInstallerLog('WARNING: ' + Message);
end;

function ReadOutputFile(const FileName: String): String;
var
  FileContents: AnsiString;
begin
  Result := '';
  if FileExists(FileName) then
  begin
    if LoadStringFromFile(FileName, FileContents) then
      Result := FileContents;
    DeleteFile(FileName);
  end;
end;

function RunRuntimeCapture(const WorkDir, Params: String; var ResultCode: Integer; var OutputText: String): Boolean;
var
  TempFile: String;
  Command: String;
begin
  TempFile := ExpandConstant('{tmp}\WarThunderRPC_runtime_output.txt');
  if FileExists(TempFile) then
    DeleteFile(TempFile);

  AppendInstallerLog('RUN ' + RuntimeExePath(WorkDir) + ' ' + Params);
  Command := '/C ""' + RuntimeExePath(WorkDir) + '" ' + Params + ' > "' + TempFile + '" 2>&1"';
  Result := Exec(ExpandConstant('{cmd}'), Command, WorkDir, SW_HIDE, ewWaitUntilTerminated, ResultCode);
  OutputText := ReadOutputFile(TempFile);
  AppendInstallerLog('EXIT ' + IntToStr(ResultCode));
  if Trim(OutputText) <> '' then
    AppendInstallerLog('OUTPUT ' + OutputText);
end;

function RunShellCapture(const Command: String; var ResultCode: Integer; var OutputText: String): Boolean;
var
  TempFile: String;
begin
  TempFile := ExpandConstant('{tmp}\WarThunderRPC_shell_output.txt');
  if FileExists(TempFile) then
    DeleteFile(TempFile);

  AppendInstallerLog('SHELL ' + Command);
  Result := Exec(
    ExpandConstant('{cmd}'),
    '/C ' + Command + ' > "' + TempFile + '" 2>&1',
    '',
    SW_HIDE,
    ewWaitUntilTerminated,
    ResultCode
  );
  OutputText := ReadOutputFile(TempFile);
  AppendInstallerLog('EXIT ' + IntToStr(ResultCode));
  if Trim(OutputText) <> '' then
    AppendInstallerLog('OUTPUT ' + OutputText);
end;

function StatusLooksHealthy(const OutputText: String): Boolean;
begin
  Result :=
    (Pos('"service_installed": true', OutputText) > 0) and
    (Pos('"service_running": true', OutputText) > 0) and
    (Pos('"task_exists": true', OutputText) > 0);
end;

procedure LogStatusDiagnostics(const OutputText: String);
begin
  if Pos('"service_installed": true', OutputText) = 0 then
    AppendInstallerLog('DIAG: service_installed is NOT true');
  if Pos('"service_running": true', OutputText) = 0 then
    AppendInstallerLog('DIAG: service_running is NOT true');
  if Pos('"task_exists": true', OutputText) = 0 then
    AppendInstallerLog('DIAG: task_exists is NOT true');
  if Pos('"status_error":', OutputText) > 0 then
    AppendInstallerLog('DIAG: status_error key present (Python-side query error)');
  if Trim(OutputText) = '' then
    AppendInstallerLog('DIAG: status output was empty');
end;

procedure CleanupExistingInstall;
var
  ResultCode: Integer;
  OutputText: String;
begin
  AppendInstallerLog('Starting cleanup of previous install state');

  if FileExists(RuntimeExePath(ExpandConstant('{app}'))) then
  begin
    RunRuntimeCapture(ExpandConstant('{app}'), '--cleanup-runtime-processes', ResultCode, OutputText);
    RunRuntimeCapture(ExpandConstant('{app}'), '--disable-controller-autostart', ResultCode, OutputText);
    RunRuntimeCapture(ExpandConstant('{app}'), '--uninstall-service', ResultCode, OutputText);
  end;

  RunShellCapture('taskkill /F /T /IM WarThunderRPC.exe', ResultCode, OutputText);
  RunShellCapture('sc stop WarThunderRPC', ResultCode, OutputText);
  RunShellCapture('sc delete WarThunderRPC', ResultCode, OutputText);
  RunShellCapture('schtasks /delete /f /tn WarThunderRPCWorker', ResultCode, OutputText);
  Sleep(2000);
  AppendInstallerLog('Finished cleanup of previous install state');
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
  SummaryLabel.Height := ScaleY(180);
  SummaryLabel.WordWrap := True;
  SummaryLabel.Caption := 'War Thunder RPC is ready to install.';
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  InstallStatusText := '';
  InstallWarnings := '';
  AppendInstallerLog('--- Starting install session ---');
  CleanupExistingInstall;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  UsernameParam: String;
  InstallParam: String;
  OutputText: String;
  StatusOutput: String;
  StatusAttempt: Integer;
  StatusVerified: Boolean;
begin
  if CurStep <> ssPostInstall then
    exit;

  UsernameParam := '--set-username ' + QuoteForParam(Trim(UsernamePage.Values[0]));
  if not RunRuntimeCapture(ExpandConstant('{app}'), UsernameParam, ResultCode, OutputText) or (ResultCode <> 0) then
    RaiseException('The installer could not save the War Thunder username for kill tracking. See ' + InstallerLogPath());

  if not RunRuntimeCapture(ExpandConstant('{app}'), '--enable-controller-autostart', ResultCode, OutputText) or (ResultCode <> 0) then
    AddInstallWarning('The controller could not be configured to start automatically. You can still launch it from the Start menu.');

  InstallParam :=
    '--install-service --runtime-path ' + QuoteForParam(RuntimeExePath(ExpandConstant('{app}')));
  if not RunRuntimeCapture(ExpandConstant('{app}'), InstallParam, ResultCode, OutputText) then
    AddInstallWarning('The install helper did not report success. Verifying final state now.')
  else if ResultCode <> 0 then
    AddInstallWarning('The install helper reported a recoverable issue. Verifying final state now.');

  Sleep(3000);

  StatusVerified := False;
  for StatusAttempt := 1 to 3 do
  begin
    if not RunRuntimeCapture(ExpandConstant('{app}'), '--status-json', ResultCode, StatusOutput) then
    begin
      AppendInstallerLog('Status attempt ' + IntToStr(StatusAttempt) + ': exec failed');
      if StatusAttempt < 3 then Sleep(3000);
      Continue;
    end;
    if StatusLooksHealthy(StatusOutput) then
    begin
      StatusVerified := True;
      Break;
    end;
    AppendInstallerLog('Status attempt ' + IntToStr(StatusAttempt) + ': not healthy yet');
    LogStatusDiagnostics(StatusOutput);
    if StatusAttempt < 3 then Sleep(3000);
  end;

  if not StatusVerified then
  begin
    LogStatusDiagnostics(StatusOutput);
    AppendInstallerLog('All status attempts failed. Last output: ' + StatusOutput);
    AddInstallWarning(
      'The service did not confirm as running during install. ' +
      'It may still start on its own. ' +
      'Check ' + InstallerLogPath() + ' if problems persist.'
    );
  end;

  if not Exec(RuntimeExePath(ExpandConstant('{app}')), '--controller', ExpandConstant('{app}'), SW_SHOWNORMAL, ewNoWait, ResultCode) then
    AddInstallWarning('The control center could not be launched automatically. You can still open it from the Start menu.');

  InstallStatusText :=
    'Install location: ' + ExpandConstant('{app}') + #13#10 +
    'Tracked username: ' + Trim(UsernamePage.Values[0]) + #13#10 +
    'Service: installed and running' + #13#10 +
    'Worker task: present' + #13#10 +
    'Controller: available from the Start menu and system tray' + #13#10#13#10 +
    'The control center now lives in the system tray. You can start War Thunder and Discord normally.';

  if InstallWarnings <> '' then
    InstallStatusText := InstallStatusText + #13#10#13#10 + 'Warnings:' + #13#10 + InstallWarnings;
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

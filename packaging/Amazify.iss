#define AppName "Amazify"
#define AppVersion "1.1.1"
#define AppPublisher "Amazify"
#define AppExeName "amazify.exe"
#define AppWindowedExeDir "amazifyw"
#define AppWindowedExeName "amazifyw.exe"
#define AppWindowedExePath "amazifyw\amazifyw.exe"
#define AmazifyAppUserModelID "Amazify.AmazonMusic"

[Setup]
AppId={{74E5EBA7-A863-4C43-9D9F-DF1F8D31D9A3}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
VersionInfoVersion={#AppVersion}.0
VersionInfoProductVersion={#AppVersion}
VersionInfoDescription=Amazify Setup
VersionInfoCompany={#AppPublisher}
VersionInfoProductName={#AppName}
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=AmazifySetup
SetupIconFile=assets\logo.ico
UninstallDisplayIcon={app}\{#AppWindowedExePath}
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ChangesEnvironment=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\dist\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\{#AppWindowedExeDir}\*"; DestDir: "{app}\{#AppWindowedExeDir}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
Type: files; Name: "{app}\{#AppWindowedExeName}"
Type: files; Name: "{group}\Amazon Music (Amazify).lnk"; Check: not IsCiSmoke
Type: files; Name: "{userprograms}\Amazon Music (Amazify).lnk"; Check: not IsCiSmoke
Type: files; Name: "{userdesktop}\Amazon Music (Amazify).lnk"; Check: not IsCiSmoke
Type: files; Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar\Amazon Music (Amazify).lnk"; Check: not IsCiSmoke

[Tasks]
Name: "startupdaemon"; Description: "Start the Amazify daemon when I sign in"; GroupDescription: "Background service:"; Flags: checkedonce
Name: "desktopicon"; Description: "Create a Desktop shortcut"; GroupDescription: "Additional shortcuts:"
Name: "taskbaricon"; Description: "Pin Amazon Music (Amazify) to the taskbar"; GroupDescription: "Additional shortcuts:"

[Icons]
Name: "{group}\Amazon Music (Amazify)"; Filename: "{app}\{#AppWindowedExePath}"; Parameters: "run"; WorkingDir: "{app}\{#AppWindowedExeDir}"; IconFilename: "{app}\{#AppWindowedExePath}"; Comment: "Launch Amazon Music through Amazify"; AppUserModelID: "{#AmazifyAppUserModelID}"; Check: not IsCiSmoke
Name: "{group}\Amazify CLI"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\{#AppExeName}"; Comment: "Open the Amazify command line"; Check: not IsCiSmoke
Name: "{userdesktop}\Amazon Music (Amazify)"; Filename: "{app}\{#AppWindowedExePath}"; Parameters: "run"; WorkingDir: "{app}\{#AppWindowedExeDir}"; IconFilename: "{app}\{#AppWindowedExePath}"; Comment: "Launch Amazon Music through Amazify"; AppUserModelID: "{#AmazifyAppUserModelID}"; Tasks: desktopicon; Check: not IsCiSmoke

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Amazify"; ValueData: """{app}\{#AppWindowedExePath}"" daemon start"; Flags: uninsdeletevalue; Tasks: startupdaemon; Check: not IsCiSmoke

[Run]
Filename: "{app}\{#AppWindowedExePath}"; Parameters: "shortcuts install --taskbar --target-exe ""{app}\{#AppWindowedExePath}"""; Flags: runhidden waituntilterminated; Tasks: taskbaricon; Check: not IsCiSmoke
Filename: "{app}\{#AppWindowedExePath}"; Parameters: "daemon start"; Flags: runhidden waituntilterminated; Check: not IsCiSmoke

[UninstallRun]
Filename: "{app}\{#AppWindowedExePath}"; Parameters: "daemon stop"; Flags: runhidden waituntilterminated; RunOnceId: "StopDaemon"; Check: not IsCiSmoke
Filename: "{app}\{#AppWindowedExePath}"; Parameters: "shortcuts remove"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveShortcuts"; Check: not IsCiSmoke

[Code]
{ ------------------------------------------------------------------ }
{  User PATH helpers                                                   }
{ ------------------------------------------------------------------ }

const
  EnvironmentRegKey = 'Environment';

function IsCiSmoke(): Boolean;
var
  Index: Integer;
  Argument: string;
begin
  Result := False;
  for Index := 1 to ParamCount do
  begin
    Argument := Uppercase(ParamStr(Index));
    if (Argument = '/CI-SMOKE') or (Argument = '/CI-SMOKE=1') then
    begin
      Result := True;
      Exit;
    end;
  end;
end;

{ Return True when InstallPath is not already present in the user PATH. }
function NeedsAddPath(const InstallPath: string): Boolean;
var
  ExistingPath: string;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, EnvironmentRegKey, 'Path', ExistingPath) then
  begin
    Result := True;
    Exit;
  end;
  Result := Pos(';' + Uppercase(InstallPath) + ';',
                ';' + Uppercase(ExistingPath) + ';') = 0;
end;

{ Append InstallPath to the user PATH if it is not already present. }
procedure AddToUserPath(const InstallPath: string);
var
  ExistingPath: string;
begin
  if not NeedsAddPath(InstallPath) then Exit;
  if not RegQueryStringValue(HKEY_CURRENT_USER, EnvironmentRegKey, 'Path', ExistingPath) then
    ExistingPath := '';
  if ExistingPath <> '' then
  begin
    if ExistingPath[Length(ExistingPath)] <> ';' then
      ExistingPath := ExistingPath + ';';
    ExistingPath := ExistingPath + InstallPath;
  end
  else
    ExistingPath := InstallPath;
  RegWriteExpandStringValue(HKEY_CURRENT_USER, EnvironmentRegKey, 'Path', ExistingPath);
end;

function NormalizePathDelimiters(PathValue: string): string;
begin
  while Pos(';;', PathValue) > 0 do
    StringChangeEx(PathValue, ';;', ';', True);
  while (PathValue <> '') and (PathValue[1] = ';') do
    Delete(PathValue, 1, 1);
  while (PathValue <> '') and (PathValue[Length(PathValue)] = ';') do
    Delete(PathValue, Length(PathValue), 1);
  Result := PathValue;
end;

{ Remove all occurrences of RemovePath from the user PATH (case-insensitive). }
procedure RemoveFromUserPath(const RemovePath: string);
var
  OldPath: string;
  UpperOld, UpperRemove: string;
  P, Len: Integer;
  Changed: Boolean;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, EnvironmentRegKey, 'Path', OldPath) then Exit;

  UpperRemove := Uppercase(RemovePath);
  Len         := Length(UpperRemove);
  Changed     := False;

  { Loop until all occurrences of RemovePath have been removed. }
  repeat
    UpperOld := Uppercase(OldPath);
    P := Pos(';' + UpperRemove + ';', ';' + UpperOld + ';');
    if P = 0 then Break;
    Changed := True;
    if P = 1 then
    begin
      { RemovePath is at the start of OldPath.  Remove "RemovePath;" (Len + 1
        chars).  If RemovePath is the only entry, Len + 1 > Length(OldPath), so
        Pascal's Delete removes everything, leaving an empty string — which is
        correct. }
      Delete(OldPath, 1, Len + 1);
    end
    else
    begin
      { RemovePath is preceded by at least one other entry.  In the padded
        string, position P is the ';' immediately before RemovePath.  That
        semicolon lives at position P - 1 in the original OldPath (because the
        padded string prepends one extra ';').  Remove ";RemovePath" = Len + 1
        chars starting at that position. }
      Delete(OldPath, P - 1, Len + 1);
    end;
  until False;

  if Changed then
  begin
    OldPath := NormalizePathDelimiters(OldPath);
    RegWriteExpandStringValue(HKEY_CURRENT_USER, EnvironmentRegKey, 'Path', OldPath);
  end;
end;

{ Stop the installed background worker before Restart Manager checks files in use.
  The daemon is windowless, so it cannot respond to a normal close-window request. }
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  DaemonExe, DaemonDir: string;
  ResultCode: Integer;
begin
  Result := '';
  if IsCiSmoke then Exit;
  DaemonExe := ExpandConstant('{app}\{#AppWindowedExePath}');
  if not FileExists(DaemonExe) then Exit;

  DaemonDir := ExtractFileDir(DaemonExe);
  if not Exec(DaemonExe, 'daemon stop', DaemonDir, SW_HIDE,
    ewWaitUntilTerminated, ResultCode) then
  begin
    Result := 'Setup could not stop the Amazify background daemon. ' +
      'Close Amazify and try the installation again.';
    Exit;
  end;

  if ResultCode <> 0 then
    Result := 'The Amazify background daemon did not stop cleanly. ' +
      'Close Amazify and try the installation again.';
end;

{ Hook: add the install directory to user PATH after installation. }
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and (not IsCiSmoke) then
  begin
    AddToUserPath(ExpandConstant('{app}'));
    if not WizardIsTaskSelected('startupdaemon') then
      RegDeleteValue(HKEY_CURRENT_USER,
        'Software\Microsoft\Windows\CurrentVersion\Run', 'Amazify');
  end;
end;

{ Hook: remove the install directory from user PATH on uninstall. }
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and (not IsCiSmoke) then
    RemoveFromUserPath(ExpandConstant('{app}'));
end;

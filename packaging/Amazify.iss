#define AppName "Amazify"
#define AppVersion "0.1.0"
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
Type: files; Name: "{group}\Amazon Music (Amazify).lnk"
Type: files; Name: "{userprograms}\Amazon Music (Amazify).lnk"
Type: files; Name: "{userdesktop}\Amazon Music (Amazify).lnk"
Type: files; Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar\Amazon Music (Amazify).lnk"

[Icons]
Name: "{group}\Amazon Music (Amazify)"; Filename: "{app}\{#AppWindowedExePath}"; Parameters: "run"; WorkingDir: "{app}\{#AppWindowedExeDir}"; IconFilename: "{app}\{#AppWindowedExePath}"; Comment: "Launch Amazon Music through Amazify"; AppUserModelID: "{#AmazifyAppUserModelID}"
Name: "{group}\Amazify CLI"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\{#AppExeName}"; Comment: "Open the Amazify command line"

[Run]
Filename: "{app}\{#AppWindowedExePath}"; Parameters: "shortcuts install --desktop --target-exe ""{app}\{#AppWindowedExePath}"""; Description: "Create Desktop shortcut"; Flags: postinstall unchecked skipifsilent runhidden waituntilterminated
Filename: "{app}\{#AppWindowedExePath}"; Parameters: "shortcuts install --taskbar --target-exe ""{app}\{#AppWindowedExePath}"""; Description: "Try to pin to taskbar"; Flags: postinstall unchecked skipifsilent runhidden waituntilterminated
Filename: "{app}\{#AppWindowedExePath}"; Parameters: "run"; Description: "Start Amazify daemon now"; Flags: nowait postinstall skipifsilent runhidden

[UninstallRun]
Filename: "{app}\{#AppWindowedExePath}"; Parameters: "daemon stop"; Flags: runhidden waituntilterminated; RunOnceId: "StopDaemon"
Filename: "{app}\{#AppWindowedExePath}"; Parameters: "shortcuts remove"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveShortcuts"

[Code]
{ ------------------------------------------------------------------ }
{  User PATH helpers                                                   }
{ ------------------------------------------------------------------ }

const
  EnvironmentRegKey = 'Environment';

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
    ExistingPath := ExistingPath + ';' + InstallPath
  else
    ExistingPath := InstallPath;
  RegWriteExpandStringValue(HKEY_CURRENT_USER, EnvironmentRegKey, 'Path', ExistingPath);
end;

{ Remove RemovePath from the user PATH (case-insensitive). }
procedure RemoveFromUserPath(const RemovePath: string);
var
  OldPath: string;
  UpperOld, UpperRemove: string;
  P, Len: Integer;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, EnvironmentRegKey, 'Path', OldPath) then Exit;

  UpperOld    := Uppercase(OldPath);
  UpperRemove := Uppercase(RemovePath);
  Len         := Length(UpperRemove);

  { Try ";RemovePath" — entry in the middle or at the end. }
  P := Pos(';' + UpperRemove + ';', ';' + UpperOld + ';');
  if P > 0 then
  begin
    { P is 1-based position inside ';'+OldPath+';'.
      The ';' before RemovePath is at position P in that augmented string,
      which corresponds to position P-1 in OldPath.
      We want to delete ";RemovePath" = 1 + Len characters starting at P-1. }
    if P = 1 then
      { Entry is at the very beginning — remove "RemovePath;" instead. }
      Delete(OldPath, 1, Len + 1)
    else
      Delete(OldPath, P - 1, Len + 1);
    RegWriteExpandStringValue(HKEY_CURRENT_USER, EnvironmentRegKey, 'Path', OldPath);
  end;
end;

{ Hook: add the install directory to user PATH after installation. }
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    AddToUserPath(ExpandConstant('{app}'));
end;

{ Hook: remove the install directory from user PATH on uninstall. }
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    RemoveFromUserPath(ExpandConstant('{app}'));
end;

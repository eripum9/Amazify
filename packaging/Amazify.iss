#define AppName "Amazify"
#define AppVersion "0.1.0"
#define AppPublisher "Amazify"
#define AppExeName "amazify.exe"
#define AppWindowedExeDir "amazifyw"
#define AppWindowedExeName "amazifyw.exe"
#define AppWindowedExePath "amazifyw\amazifyw.exe"

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

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\dist\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\{#AppWindowedExeDir}\*"; DestDir: "{app}\{#AppWindowedExeDir}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
Type: files; Name: "{app}\{#AppWindowedExeName}"

[Icons]
Name: "{group}\Amazon Music (Amazify)"; Filename: "{app}\{#AppWindowedExePath}"; Parameters: "run"; WorkingDir: "{app}\{#AppWindowedExeDir}"; IconFilename: "{app}\{#AppWindowedExePath}"; Comment: "Launch Amazon Music through Amazify"
Name: "{group}\Amazify CLI"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\{#AppExeName}"; Comment: "Open the Amazify command line"

[Run]
Filename: "{app}\{#AppWindowedExePath}"; Parameters: "shortcuts install --desktop --target-exe ""{app}\{#AppWindowedExePath}"""; Description: "Create Desktop shortcut"; Flags: postinstall unchecked skipifsilent runhidden waituntilterminated
Filename: "{app}\{#AppWindowedExePath}"; Parameters: "shortcuts install --taskbar --target-exe ""{app}\{#AppWindowedExePath}"""; Description: "Try to pin to taskbar"; Flags: postinstall unchecked skipifsilent runhidden waituntilterminated
Filename: "{app}\{#AppWindowedExePath}"; Parameters: "run"; Description: "Start Amazify daemon now"; Flags: nowait postinstall skipifsilent runhidden

[UninstallRun]
Filename: "{app}\{#AppWindowedExePath}"; Parameters: "daemon stop"; Flags: runhidden waituntilterminated; RunOnceId: "StopDaemon"
Filename: "{app}\{#AppWindowedExePath}"; Parameters: "shortcuts remove"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveShortcuts"

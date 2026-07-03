#define AppName "Amazify"
#define AppVersion "0.1.0"
#define AppPublisher "Amazify"
#define AppExeName "amazify.exe"
#define AppWindowedExeName "amazifyw.exe"

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
UninstallDisplayIcon={app}\{#AppWindowedExeName}
PrivilegesRequired=lowest
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
Compression=lzma
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\dist\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\{#AppWindowedExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Amazon Music (Amazify)"; Filename: "{app}\{#AppWindowedExeName}"; Parameters: "run"; WorkingDir: "{app}"; IconFilename: "{app}\{#AppWindowedExeName}"; Comment: "Launch Amazon Music through Amazify"
Name: "{group}\Amazify CLI"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\{#AppExeName}"; Comment: "Open the Amazify command line"

[Run]
Filename: "{app}\{#AppWindowedExeName}"; Parameters: "shortcuts install --desktop --target-exe ""{app}\{#AppWindowedExeName}"""; Description: "Create Desktop shortcut"; Flags: postinstall unchecked skipifsilent runhidden waituntilterminated
Filename: "{app}\{#AppWindowedExeName}"; Parameters: "shortcuts install --taskbar --target-exe ""{app}\{#AppWindowedExeName}"""; Description: "Try to pin to taskbar"; Flags: postinstall unchecked skipifsilent runhidden waituntilterminated
Filename: "{app}\{#AppWindowedExeName}"; Parameters: "run"; Description: "Start Amazify daemon now"; Flags: nowait postinstall skipifsilent runhidden

[UninstallRun]
Filename: "{app}\{#AppWindowedExeName}"; Parameters: "daemon stop"; Flags: runhidden waituntilterminated
Filename: "{app}\{#AppWindowedExeName}"; Parameters: "shortcuts remove"; Flags: runhidden waituntilterminated

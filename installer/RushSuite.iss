; RushSuite installer (Inno Setup 6). Built by GitHub Actions from dist\RushSuite.
#define AppName "RushSuite"
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{6C1E2B7A-5D2E-4E4B-9B1D-52A1F0C3D7E9}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=RushSuite
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\release
OutputBaseFilename=RushSuite-Setup-{#AppVersion}
SetupIconFile=..\app\assets\icon.ico
UninstallDisplayIcon={app}\RushSuite.exe
Compression=lzma2/max
SolidCompression=no
LZMANumBlockThreads=4
DiskSpanning=yes
DiskSliceSize=1900000000
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\RushSuite\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__\*,*.pyc"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\RushSuite.exe"
Name: "{group}\RushSuite self-test"; Filename: "{app}\Run self-test.bat"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\RushSuite.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\RushSuite.exe"; Description: "Start RushSuite"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\app\__pycache__"

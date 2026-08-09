#define MyAppName "BiliCut"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "BiliCut"
#define MyAppExeName "BiliCut.exe"

[Setup]
AppId={{B3F42DCE-832D-41B7-A70E-46DA85B08D67}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}

DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest

OutputDir=..\release
OutputBaseFilename=BiliCut-Setup-{#MyAppVersion}

SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}

Compression=lzma2
SolidCompression=yes
WizardStyle=modern

ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

CloseApplications=yes
DisableProgramGroupPage=yes

[Tasks]
Name: "desktopicon"; \
    Description: "Tạo biểu tượng ngoài màn hình"; \
    GroupDescription: "Tùy chọn:"

[Files]
Source: "..\dist\BiliCut\*"; \
    DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; \
    Filename: "{app}\{#MyAppExeName}"; \
    WorkingDir: "{app}"

Name: "{autodesktop}\{#MyAppName}"; \
    Filename: "{app}\{#MyAppExeName}"; \
    WorkingDir: "{app}"; \
    Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; \
    Description: "Khởi động {#MyAppName}"; \
    Flags: nowait postinstall skipifsilent
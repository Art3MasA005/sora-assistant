; Sora — Windows installer (Inno Setup 6).
; Build with:  powershell -File windows\installer\build.ps1   (from app/)
; Output:      build\installer\Sora-Setup-<version>.exe

#define AppName "Sora"
#define AppVersion "1.0.7"
#define AppExe "sora.exe"
#define BuildDir "..\..\build\windows\x64\runner\Release"

[Setup]
AppId={{6F1C2B7E-5A3D-4E8B-9C21-3B7D5E9A0F14}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Yeasir
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Per-user install: no admin prompt, goes to %LOCALAPPDATA%\Programs\Sora.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\build\installer
OutputBaseFilename=Sora-Setup-{#AppVersion}
SetupIconFile=..\runner\resources\app_icon.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#BuildDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; build.ps1 copies the 64-bit MSVC runtime DLLs into BuildDir, so a PC without
; the VC++ redistributable still runs Sora.

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Sora keeps running in the notification area after its window is closed: end it first (tray icon
; and all), or it would stay running and its files couldn't be removed.
Filename: "{app}\{#AppExe}"; Parameters: "--quit"; Flags: runhidden waituntilterminated; RunOnceId: "QuitSora"

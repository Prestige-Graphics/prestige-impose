; Inno Setup recipe for the Windows installer.
;
;   iscc /DAppVersion=1.0.0 packaging\windows_installer.iss
;
; Installs for the current user only (no admin prompt), into
; %LOCALAPPDATA%\Programs\Prestige Impose. The same installer is used for
; updates: the app runs it silently and it reopens the app when done.

#ifndef AppVersion
  #error Pass the version: iscc /DAppVersion=1.2.3
#endif

#define AppName "Prestige Impose"
#define AppExe "Prestige Impose.exe"
#define AppUserModelID "PrestigeGraphics.Impose"
#define ProgId "PrestigeGraphics.Impose.pdf"

[Setup]
AppId={{4C00C6FC-16C3-495A-B99C-6A8F90250A8D}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Prestige Graphics Inc.
DefaultDirName={localappdata}\Programs\{#AppName}
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=PrestigeImpose-Setup-{#AppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
CloseApplications=force
RestartApplications=no
ChangesAssociations=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[InstallDelete]
; Clear the previous version's libraries so nothing stale is left behind.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\{#AppName}\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{userprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "{#AppUserModelID}"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "{#AppUserModelID}"; Tasks: desktopicon

[Registry]
; Right-click a PDF > Open with > Prestige Impose (doesn't change the default PDF app)
Root: HKCU; Subkey: "Software\Classes\{#ProgId}"; ValueType: string; ValueData: "PDF (Prestige Impose)"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\{#ProgId}"; ValueType: string; ValueName: "FriendlyTypeName"; ValueData: "PDF document"
Root: HKCU; Subkey: "Software\Classes\{#ProgId}\DefaultIcon"; ValueType: string; ValueData: """{app}\{#AppExe}"",0"
Root: HKCU; Subkey: "Software\Classes\{#ProgId}\Application"; ValueType: string; ValueName: "ApplicationName"; ValueData: "{#AppName}"
Root: HKCU; Subkey: "Software\Classes\{#ProgId}\Application"; ValueType: string; ValueName: "ApplicationIcon"; ValueData: """{app}\{#AppExe}"",0"
Root: HKCU; Subkey: "Software\Classes\{#ProgId}\Application"; ValueType: string; ValueName: "AppUserModelID"; ValueData: "{#AppUserModelID}"
Root: HKCU; Subkey: "Software\Classes\{#ProgId}\shell\open"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "{#AppName}"
Root: HKCU; Subkey: "Software\Classes\{#ProgId}\shell\open\command"; ValueType: string; ValueData: """{app}\{#AppExe}"" ""%1"""
Root: HKCU; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: string; ValueName: "{#ProgId}"; ValueData: ""; Flags: uninsdeletevalue
; Right-click a PDF > Show more options > Impose with Prestige Impose
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\PrestigeImpose"; ValueType: string; ValueData: "Impose with {#AppName}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\PrestigeImpose"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#AppExe}"",0"
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\PrestigeImpose\command"; ValueType: string; ValueData: """{app}\{#AppExe}"" ""%1"""

[Run]
; Opens the app after a normal install, and after a silent self-update.
Filename: "{app}\{#AppExe}"; Description: "Open {#AppName}"; Flags: nowait postinstall

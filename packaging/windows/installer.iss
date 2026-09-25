; Cinefin Windows installer (Inno Setup 6). Built by build.ps1, which passes
; /DAppVersion. Per-user install (no admin): the app lives under the user's
; local programs dir and "run at login" uses HKCU, so nothing needs elevation.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{D9F2A6E1-3C4B-4E9A-9F2C-CINEFINWIN}}
AppName=Cinefin
AppVersion={#AppVersion}
AppPublisher=Cinefin
DefaultDirName={localappdata}\Programs\Cinefin
DefaultGroupName=Cinefin
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=Output
OutputBaseFilename=Cinefin-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=cinefin.ico
UninstallDisplayIcon={app}\Cinefin.exe

[Tasks]
Name: "startuplogin"; Description: "Start Cinefin automatically when I log in"; Flags: unchecked

[Files]
; The whole PyInstaller one-folder bundle.
Source: "dist\Cinefin\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\Cinefin"; Filename: "{app}\Cinefin.exe"
Name: "{userdesktop}\Cinefin"; Filename: "{app}\Cinefin.exe"; Tasks: startuplogin
; Startup shortcut (created only if the task is chosen).
Name: "{userstartup}\Cinefin"; Filename: "{app}\Cinefin.exe"; Tasks: startuplogin

[Run]
Filename: "{app}\Cinefin.exe"; Description: "Launch Cinefin now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Remove the frozen app; user data under %LOCALAPPDATA%\Cinefin is left intact.
Type: filesandordirs; Name: "{app}"

; Cinefin Windows installer (Inno Setup 6). Packages the staged tree built by
; build.ps1 (a relocatable Python with cinefin pip-installed, ffmpeg, the tray).
; Per-user install (no admin): app under the user's local programs dir, "run at
; login" via HKCU. build.ps1 passes /DAppVersion and /DStageDir.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef StageDir
  #define StageDir "stage"
#endif

[Setup]
AppId={{D9F2A6E1-3C4B-4E9A-9F2C-CINEFINWIN}}
AppName=Cinefin
AppVersion={#AppVersion}
AppPublisher=Cinefin
DefaultDirName={localappdata}\Programs\Cinefin
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=Output
OutputBaseFilename=Cinefin-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile={#StageDir}\cinefin.ico
UninstallDisplayIcon={app}\python\pythonw.exe

[Tasks]
Name: "startuplogin"; Description: "Start Cinefin automatically when I log in"; Flags: unchecked

[Files]
Source: "{#StageDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
; Launch the tray with the bundled windowless interpreter.
Name: "{group}\Cinefin"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\tray.py"""; WorkingDir: "{app}"; IconFilename: "{app}\cinefin.ico"
Name: "{userstartup}\Cinefin"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\tray.py"""; WorkingDir: "{app}"; Tasks: startuplogin

[Run]
Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\tray.py"""; WorkingDir: "{app}"; Description: "Launch Cinefin now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Remove the app; user data under %LOCALAPPDATA%\Cinefin is left intact.
Type: filesandordirs; Name: "{app}"

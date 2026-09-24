; Recruiting Desk -- Windows installer
;
; Built by GitHub Actions on every tagged release (see .github/workflows).
; To build by hand on Windows: install Inno Setup 6, build the app with
; PyInstaller first, then run
;     iscc installer\recruiting_desk.iss /DAppVersion=0.1.0
;
; Installs per-user into %LOCALAPPDATA%\Programs, so no administrator rights
; are needed -- most parents are not admins on a work laptop, and a UAC prompt
; is the moment a cautious person closes the installer.
;
; The family's data lives in %APPDATA%\RecruitingDesk and is deliberately NOT
; removed on uninstall. Reinstalling or upgrading must never cost anyone their
; coach list. The uninstaller says so.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

#define AppName "Recruiting Desk"
#define AppExe  "Recruiting Desk.exe"

[Setup]
AppId={{6C4E2F1A-9B7D-4E3A-8F21-5D0C7B9A3E64}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Sean Rugge
AppPublisherURL=https://github.com/seanrugg/recruiter_assistant
AppSupportURL=https://github.com/seanrugg/recruiter_assistant/issues
DefaultDirName={localappdata}\Programs\RecruitingDesk
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=RecruitingDesk-Setup-{#AppVersion}
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Put a shortcut on the desktop"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\RecruitingDesk\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Open Recruiting Desk now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Stop a running copy so its files can be removed.
Filename: "{cmd}"; Parameters: "/C taskkill /IM ""{#AppExe}"" /F"; Flags: runhidden; RunOnceId: "StopApp"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    MsgBox('Recruiting Desk has been removed.' + #13#10 + #13#10 +
           'Player records, coach lists and settings were kept, in case you reinstall. ' +
           'To delete them too, remove this folder:' + #13#10 + #13#10 +
           ExpandConstant('{userappdata}\RecruitingDesk'),
           mbInformation, MB_OK);
end;

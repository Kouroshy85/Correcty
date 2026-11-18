; Inno Setup 6 script for Correcty.
; Build the app first (dist\Correcty), then from the project folder:
;   "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer\installer.iss
; Output: installer\Output\Correcty-Setup-<version>.exe
;
; Templates live in %APPDATA%\Correcty. Setup never writes there and uninstall never removes it,
; so templates survive upgrades and uninstalls.

#define AppName "Correcty"
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define AppExe "Correcty.exe"

[Setup]
; Keep this AppId forever: upgrades and uninstall find the existing install by it.
AppId={{E623EF95-77C6-4E74-B6C9-60DF99921B71}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Kouroshy85
LicenseFile=..\LICENSE
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=Output
OutputBaseFilename=Correcty-Setup-{#AppVersion}
SetupIconFile=correcty.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; Drop files left over from an older build before copying the new one.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\Correcty\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; Comment: "Open Correcty in your browser"
Name: "{autoprograms}\Stop {#AppName}"; Filename: "{app}\{#AppExe}"; Parameters: "--stop"; Comment: "Stop Correcty running in the background"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
; postinstall entries run as the user who started Setup (not elevated), so the data goes to their %APPDATA%.
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Code]
// Correcty has no window, so Windows can't ask it to close. Stop a running copy before files are replaced or removed.
procedure StopRunningApp();
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM "{#AppExe}"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopRunningApp();
  Result := '';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    StopRunningApp();
end;

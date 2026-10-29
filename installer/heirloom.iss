; Heirloom's Windows installer, built with Inno Setup 6 (https://jrsoftware.org/isinfo.php) from PyInstaller's
; folder build in installer\build\heirloom (installer\heirloom.spec, see .github/workflows/build-base.yml):
;   iscc /DAppVersion=0.24.0 installer\heirloom.iss
; The shortcuts run heirloom-gui.exe, a windowed program that opens the window without any terminal showing.
; It installs for the current user, so it needs no administrator rights, and leaves the config folder
; (~/.config/heirloom, with the login and game list) in place when uninstalling.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "build\heirloom"
#endif

[Setup]
; never change: it is how installers of newer versions find and upgrade an installation
AppId={{BC506EB3-601E-4DAD-9477-359D537BF98F}
AppName=Heirloom
AppVersion={#AppVersion}
AppPublisher=Heirloom
AppPublisherURL=https://github.com/tuskilicious/heirloom
AppSupportURL=https://github.com/tuskilicious/heirloom/issues
AppUpdatesURL=https://github.com/tuskilicious/heirloom/releases
DefaultDirName={autopf}\Heirloom
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
ChangesEnvironment=yes
OutputDir=Output
OutputBaseFilename=heirloom_windows_x64_setup
SetupIconFile=..\assets\windows_icon.ico
UninstallDisplayIcon={app}\heirloom.exe
UninstallDisplayName=Heirloom
WizardStyle=modern
Compression=lzma2
SolidCompression=yes

[Tasks]
Name: "addtopath"; Description: "Add Heirloom to PATH, to use the ""heirloom"" command in a terminal"
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; files of the previous version that this one may not have
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Heirloom"; Filename: "{app}\heirloom-gui.exe"; Comment: "Your Epic Games library"
Name: "{autodesktop}\Heirloom"; Filename: "{app}\heirloom-gui.exe"; Comment: "Your Epic Games library"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}"; Tasks: addtopath; Check: NotInPath

[Run]
Filename: "{app}\heirloom-gui.exe"; Description: "Open Heirloom"; Flags: nowait postinstall skipifsilent

[Code]
function PathEntry(Path: string): Integer;
begin
  Result := Pos(';' + Uppercase(ExpandConstant('{app}')) + ';', ';' + Uppercase(Path) + ';');
end;

function NotInPath(): Boolean;
var
  Path: string;
begin
  Result := not RegQueryStringValue(HKCU, 'Environment', 'Path', Path) or (PathEntry(Path) = 0);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Path: string;
  Entry: Integer;
begin
  if (CurUninstallStep <> usPostUninstall) or not RegQueryStringValue(HKCU, 'Environment', 'Path', Path) then
    Exit;
  Entry := PathEntry(Path);
  if Entry = 0 then
    Exit;
  Path := ';' + Path + ';';
  Delete(Path, Entry, Length(ExpandConstant('{app}')) + 1);
  RegWriteExpandStringValue(HKCU, 'Environment', 'Path', Copy(Path, 2, Length(Path) - 2));
end;

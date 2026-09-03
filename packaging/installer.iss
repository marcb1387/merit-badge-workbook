; Inno Setup script for Merit Badge Workbook.
;
; Build the PyInstaller bundle first, then compile this:
;   python -m PyInstaller packaging/mbworkbook.spec --noconfirm
;   "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" packaging\installer.iss
;
; Installs per-user by default. A troop volunteer on a work or school laptop
; usually cannot elevate, and nothing here needs machine-wide access.

#define AppName        "Merit Badge Workbook"
#define AppVersion     "1.1.0"
#define AppPublisher   "Merit Badge Workbook"
#define AppURL         "https://github.com/marcb1387/merit-badge-workbook"
#define GuiExe         "MeritBadgeWorkbook.exe"
#define CliExe         "mbworkbook.exe"
#define SourceDir      "..\dist\MeritBadgeWorkbook"

[Setup]
AppId={{8E4C2F13-5D7A-4B96-9C1E-2A6F8D3B7E45}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases

; Per-user install: no UAC prompt, no admin rights needed.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
AllowNoIcons=yes

OutputDir=..\dist
OutputBaseFilename=MeritBadgeWorkbook-{#AppVersion}-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

; Qt is 64-bit only.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#GuiExe}
LicenseFile=..\LICENSE
InfoBeforeFile=before-install.txt

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; \
    GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "addtopath"; Description: "Add the mbworkbook command to PATH"; \
    GroupDescription: "Command line"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#GuiExe}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#GuiExe}"; Tasks: desktopicon

[Registry]
; Only touch the user's own PATH, and only if they asked for it.
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; \
    ValueData: "{olddata};{app}"; Tasks: addtopath; \
    Check: NeedsAddPath(ExpandConstant('{app}'))

[Run]
Filename: "{app}\{#GuiExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; The page cache is regenerable and belongs to us; settings are the user's, so
; those are deliberately left behind in case they reinstall.
Type: filesandordirs; Name: "{localappdata}\MeritBadgeWorkbook\Cache"

[Code]
{ Do not append our directory to PATH a second time on reinstall. }
function NeedsAddPath(Param: string): Boolean;
var
  OrigPath: string;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', OrigPath) then
  begin
    Result := True;
    exit;
  end;
  Result := Pos(';' + Uppercase(Param) + ';', ';' + Uppercase(OrigPath) + ';') = 0;
end;

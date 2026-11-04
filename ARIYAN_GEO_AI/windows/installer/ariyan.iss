; ARIYAN GEO AI for Windows -- installer (win-w5a, 2026-11-04), built by Inno Setup 6 on GitHub.
; Installs for the current user only (no administrator rights), so it works on a managed laptop.
; The data folder (%USERPROFILE%\ARIYAN_GEO_AI\offline_data), the settings and the saved keys
; (%APPDATA%\ARIYAN_GEO_AI) are never written or removed by this installer or its uninstaller.
;
; Built with:  iscc /DAppVer=win-w5a /DBuildNo=123 /DSourceDir="..\dist\ARIYAN GEO AI" ariyan.iss

#ifndef AppVer
  #define AppVer "dev"
#endif
#ifndef BuildNo
  #define BuildNo "0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\ARIYAN GEO AI"
#endif

#define AppName "ARIYAN GEO AI"
#define AppExe "ARIYAN GEO AI.exe"

[Setup]
; never change AppId: it is how a new version finds and updates the installed one
AppId={{6F2B8E1C-5A3D-4C7B-9E21-A1D0C0FFEE51}
AppName={#AppName}
AppVersion={#AppVer} (build {#BuildNo})
AppVerName={#AppName} {#AppVer}
AppPublisher=ARIYAN GEO AI
AppComments=Scientific Geospatial Laboratory - Evidence. Reasoning. Confidence.
VersionInfoVersion=1.0.0.{#BuildNo}
VersionInfoDescription={#AppName} installer
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; the program folder is fixed: the uninstaller removes it, so it must never be a folder that holds data
DisableDirPage=yes
UsePreviousAppDir=no
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=output
OutputBaseFilename=ARIYAN_GEO_AI_Setup_{#AppVer}
SetupIconFile=..\ariyan_win\assets\ariyan.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes
RestartApplications=no
InfoBeforeFile=before_install.txt
MinVersion=10.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Put an {#AppName} icon on the desktop"; GroupDescription: "Shortcuts:"

[InstallDelete]
; a new version replaces the old program files completely (never the data folder, which is elsewhere)
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; Comment: "Scientific Geospatial Laboratory"
Name: "{autoprograms}\{#AppName} self-test"; Filename: "{app}\{#AppExe}"; Parameters: "--selftest"; Comment: "Checks the installed program; writes %TEMP%\ariyan_selftest.txt"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Open {#AppName} now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; only the program folder; the data folder and %APPDATA%\ARIYAN_GEO_AI stay where they are
Type: filesandordirs; Name: "{app}"

[Messages]
FinishedLabel=Setup has installed [name] on this computer.%n%nYour data folder, settings, keys and Google Drive sign-in were not touched. Open the program from the Start menu or the desktop icon.

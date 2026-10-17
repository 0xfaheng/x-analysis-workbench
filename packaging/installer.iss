; 编译：ISCC.exe /DAppVersion=2.0.0 packaging\installer.iss
#ifndef AppVersion
  #error AppVersion must be supplied with /DAppVersion
#endif
#define AppName "X 分析工作台"

[Setup]
AppId={{33D8DF72-F428-4FA0-8B95-91BA6ACF3DE7}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=XWorkbench
DefaultDirName={localappdata}\Programs\XWorkbench
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=XWorkbench-Setup-{#AppVersion}
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\XWorkbench.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Languages]
#if FileExists(AddBackslash(CompilerPath) + "Languages\ChineseSimplified.isl")
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
#elif FileExists(AddBackslash(CompilerPath) + "Languages\Unofficial\ChineseSimplified.isl")
Name: "chinesesimp"; MessagesFile: "compiler:Languages\Unofficial\ChineseSimplified.isl"
#elif FileExists(AddBackslash(CompilerPath) + "Unofficial\ChineseSimplified.isl")
Name: "chinesesimp"; MessagesFile: "compiler:Unofficial\ChineseSimplified.isl"
#else
Name: "english"; MessagesFile: "compiler:Default.isl"
#endif

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："; Flags: unchecked

[Files]
Source: "..\dist\XWorkbench\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\XWorkbench.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\XWorkbench.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\XWorkbench.exe"; Description: "启动 {#AppName}"; Flags: nowait postinstall skipifsilent

; 不配置用户数据的 UninstallDelete；Documents\X分析工作台 完整保留。

; mpau 发布台 安装包脚本 (Inno Setup 6)
; 由 tools/build_installer.py 调用 ISCC 编译; 路径相对于本文件所在目录(tools/)
; 版本号以 pyproject.toml 为唯一来源: build_installer.py 会传 /DMyAppVersion=<version>;
; 下面的默认值仅供"直接跑 ISCC 不传参"时兜底, 改版本请改 pyproject.toml
#define MyAppName "mpau 发布台"
#ifndef MyAppVersion
  #define MyAppVersion "0.1.3"
#endif
#define MyAppPublisher "mpau"
#define MyAppExeName "mpau-launcher.exe"

[Setup]
AppId={{8C4F2E1A-7B3D-4E5F-9A6C-1D2B3E4F5A67}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\mpau
PrivilegesRequired=lowest
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
OutputDir=..\package\dist
OutputBaseFilename=mpau-setup-{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
UninstallDisplayName={#MyAppName}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"
Name: "autostart"; Description: "开机自动启动(登录 Windows 后后台自动就绪)"; GroupDescription: "附加任务:"; Flags: unchecked

[Files]
Source: "..\package\build\staging\app\*"; DestDir: "{app}\app"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\package\build\staging\python\*"; DestDir: "{app}\python"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\package\build\staging\mpau-launcher.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\package\build\staging\kernels\ms-playwright\*"; DestDir: "{localappdata}\ms-playwright"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userstartmenu}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "mpau"; ValueType: string; ValueData: """{app}\{#MyAppExeName}"""; Tasks: autostart; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即启动 mpau 发布台"; Flags: nowait postinstall skipifsilent

[InstallDelete]
; 清理 0.1.0 版释放的 playwright 内核(1234 系), 现全平台统一走 patchright 1208 系
Type: filesandordirs; Name: "{localappdata}\ms-playwright\chromium-1234"
Type: filesandordirs; Name: "{localappdata}\ms-playwright\chromium_headless_shell-1234"

[Code]
{ 覆盖安装前结束后台驻留进程: pythonw/launcher 是无窗口进程, Inno 的自动关闭机制够不到, 手动按路径清理;
  UI 窗口与上传器用的内置 Chromium 在 ms-playwright 下运行, 也一并关掉, 否则内核文件被占用导致安装失败 }
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
  AppPath, KernelPath: String;
begin
  AppPath := ExpandConstant('{app}');
  KernelPath := ExpandConstant('{localappdata}') + '\ms-playwright';
  Exec('powershell.exe',
    '-NoProfile -WindowStyle Hidden -Command "Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -like ''' +
    AppPath + '\*'' -or $_.ExecutablePath -like ''' + KernelPath + '\*'' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := '';
end;

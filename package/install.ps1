# mpau 一键安装器(单包版: 项目代码 + 浏览器内核)
# 用法一(在线): powershell -ExecutionPolicy Bypass -Command "irm http://192.168.1.216:8898/package/install.ps1 | iex"
# 用法二(离线, 推荐给外部使用者): 双击同目录 setup.bat, 或在 PowerShell 里:
#   powershell -ExecutionPolicy Bypass -File .\install.ps1 -OfflineZip "D:\mpau.zip"
# 参数:
#   -Server       安装包服务器地址, 默认 http://192.168.1.216:8898
#   -InstallDir   安装目录, 默认 D:\mpau-auto-upload
#   -OfflineZip   离线模式: 本地 zip 路径(内含浏览器内核, 除 Python 依赖外不联网)
#   -AutoStart    直接注册开机自启(不询问)
#   -NoAutoStart  不注册开机自启(不询问)
#   -SkipLaunch   装完不自动启动服务/不打开浏览器(静默安装场景)

param(
    [string]$Server = "http://192.168.1.216:8898",
    [string]$InstallDir = "D:\mpau-auto-upload",
    [string]$OfflineZip = "",
    [switch]$AutoStart,
    [switch]$NoAutoStart,
    [switch]$SkipLaunch
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$Mirror = "https://pypi.tuna.tsinghua.edu.cn/simple"

function Say($msg, $color = "Cyan") { Write-Host $msg -ForegroundColor $color }

Say ""
Say "=============================================="
Say "  mpau 多平台自动上传 · 一键安装器"
Say "=============================================="
Say ""

# ---------- 0. 下载安装包 ----------
$tmp = Join-Path $env:TEMP "mpau_install"
New-Item -ItemType Directory -Force -Path $tmp | Out-Null
$projectZip = Join-Path $tmp "mpau.zip"

if ($OfflineZip -and (Test-Path $OfflineZip)) {
    $projectZip = $OfflineZip
    Say "离线模式: 安装包 $OfflineZip"
} else {
    Say "正在从服务器下载安装包(约 320MB): $Server/package/mpau.zip"
    Invoke-WebRequest -Uri "$Server/package/mpau.zip" -OutFile $projectZip -TimeoutSec 900
}

# ---------- 1. 检查 Python / uv ----------
$pyOk = $false
try { $pv = python --version 2>&1; if ($LASTEXITCODE -eq 0 -and $pv -match "3\.(1[0-2])") { $pyOk = $true } } catch { }
if (-not $pyOk) {
    try { $pv = py -3 --version 2>&1; if ($LASTEXITCODE -eq 0 -and $pv -match "3\.(1[0-2])") { $pyOk = $true; Say "使用 py 启动器: $pv" } } catch { }
}
$pyExe = "python"
if (-not $pyOk) {
    # winget 自动安装 Python 3.12(微软官方渠道, 装到 %LOCALAPPDATA%\Programs\Python)
    Say "未检测到 Python, 尝试用 winget 自动安装 Python 3.12..."
    $ErrorActionPreference = "Continue"
    winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements 2>&1 | Out-Null
    $wg = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
    $wingetPy = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
    if ($wg -eq 0 -and (Test-Path $wingetPy)) {
        $pyOk = $true; $pyExe = $wingetPy
        $pv = & $wingetPy --version 2>&1
        Say "Python(winget 自动安装): $pv"
    }
}
if (-not $pyOk) {
    Say "未找到 Python 3.10-3.12, 且 winget 自动安装失败。请手动安装(官网 https://www.python.org/downloads/ 或微软商店搜索 Python 3.12, 勾选 Add to PATH), 然后重跑本脚本。" "Yellow"
    exit 1
}
Say "Python: $pv"

$uvOk = $false
try { $uvv = uv --version 2>&1; if ($LASTEXITCODE -eq 0) { $uvOk = $true } } catch { }
$uvCmd = "uv"          # uv 可执行文件(uv.exe 或 python.exe)
$uvMod = $false        # $true 时通过 "python -m uv" 调用(无需 PATH 刷新)
if (-not $uvOk) {
    Say "未找到 uv, 正在自动安装..."
    $ErrorActionPreference = "Continue"
    & $pyExe -m pip install -q -i $Mirror uv 2>&1 | Out-Null
    $pipExit = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
    if ($pipExit -eq 0) {
        # pip 刚装完, 当前进程 PATH 未刷新; 统一走 python -m uv(不依赖 Scripts 路径猜测,
        # 兼容官网/微软商店/winget 各种 Python 安装位置)
        try { $pyReal = (Get-Command $pyExe -ErrorAction Stop).Source } catch { $pyReal = "" }
        if (-not $pyReal) { $pyReal = $pyExe }
        $uvCmd = $pyReal; $uvMod = $true
        $uvOk = $true; Say "uv 安装完成(经 python -m uv 调用)"
    } else { Say "uv 自动安装失败, 请手动执行: pip install uv" "Yellow"; exit 1 }
}

function Invoke-Uv {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$UvArgs)
    if ($script:uvMod) {
        & $script:uvCmd -m uv @UvArgs
    } else {
        & $script:uvCmd @UvArgs
    }
}

# ---------- 2. 解压安装包 ----------
Say "解压安装包(约 1-3 分钟)..."
$extract = Join-Path $tmp "extract"
if (Test-Path $extract) { Remove-Item $extract -Recurse -Force }
Expand-Archive -Path $projectZip -DestinationPath $extract -Force

if (Test-Path $InstallDir) { Remove-Item $InstallDir -Recurse -Force }
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Get-ChildItem $extract -Force | Where-Object { $_.Name -ne "ms-playwright" } | ForEach-Object {
    Copy-Item $_.FullName (Join-Path $InstallDir $_.Name) -Recurse -Force
}
Say "项目代码已解压到 $InstallDir"

# ---------- 3. 安装依赖 ----------
Set-Location $InstallDir
$env:UV_INDEX_URL = $Mirror
# 优先用 uv 托管 Python(自带 VC 运行库): 避免系统 Python 缺 DLL(greenlet 加载失败)等环境问题
$env:UV_PYTHON_PREFERENCE = "managed"
$env:UV_PYTHON_INSTALL_MIRROR = "https://registry.npmmirror.com/-/binary/python-build-standalone"
Say "安装依赖(uv 托管 Python 3.12 + 清华镜像, 约 2-5 分钟)..."
# PS5.1 会把原生命令的 stderr 当错误, 这里临时放宽
$ErrorActionPreference = "Continue"
Invoke-Uv sync --extra web 2>&1 | Select-Object -Last 3 | ForEach-Object { Write-Host $_ -ForegroundColor DarkGray }
$uvExit = $LASTEXITCODE
if ($uvExit -ne 0) {
    # 托管 Python 下载失败(如无外网)时, 回退系统 Python 再试一次
    Say "托管 Python 不可用, 回退使用系统 Python 重试..." "Yellow"
    Remove-Item Env:UV_PYTHON_PREFERENCE -ErrorAction SilentlyContinue
    Invoke-Uv sync --extra web 2>&1 | Select-Object -Last 3 | ForEach-Object { Write-Host $_ -ForegroundColor DarkGray }
    $uvExit = $LASTEXITCODE
}
$ErrorActionPreference = "Stop"
if ($uvExit -ne 0) {
    Say "依赖安装失败, 请把上面错误发给技术支持。" "Red"
    exit 1
}
# 验证 C 扩展可加载(系统 Python 缺 VC++ 运行库时 greenlet 会 DLL 加载失败)
# 注意: 验证期间必须临时放宽 EAP 并抑制 stderr, 否则 PS5.1 会把 python 的 stderr 当 NativeCommandError 中止脚本
$ErrorActionPreference = "Continue"
$glOut = & .venv\Scripts\python.exe -c "import greenlet, patchright" 2>&1 | Out-String
$glExit = $LASTEXITCODE
$ErrorActionPreference = "Stop"
if ($glExit -ne 0) {
    Say "警告: greenlet/patchright 加载失败(退出码 $glExit):" "Red"
    $glOut -split "`r?`n" | Where-Object { $_.Trim() } | Select-Object -First 8 | ForEach-Object { Say "  $_" "DarkGray" }
    Say "  若提示缺少 DLL: 安装微软运行库后重跑 https://aka.ms/vs/17/release/vc_redist.x64.exe" "Yellow"
}
Say "依赖安装完成"

# ---------- 4. 浏览器检查(系统 Chrome 或安装包内置内核, 有其一即可) ----------
$chrome = @("$env:ProgramFiles\Google\Chrome\Application\chrome.exe", "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe", "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe") | Where-Object { Test-Path $_ }
$bundledKernel = Get-ChildItem (Join-Path $extract "ms-playwright") -Directory -Filter "chromium-*" -ErrorAction SilentlyContinue | Where-Object { Test-Path (Join-Path $_.FullName "chrome-win64\chrome.exe") } | Select-Object -First 1
if ($chrome) {
    Say "浏览器: 已检测到 Google Chrome"
} elseif ($bundledKernel) {
    Say "浏览器: 未检测到系统 Google Chrome, 将自动使用安装包内置浏览器内核" "Yellow"
    Say "         (有头模式登录与 Chrome 表现一致; 若登录遇验证码, 建议安装 Chrome)" "DarkGray"
} else {
    Say "警告: 未检测到 Google Chrome 且安装包内无浏览器内核, 发布功能会失败。请先安装 Chrome。" "Red"
}

# ---------- 5. 浏览器内核(Playwright/patchright, 上传发布必需) ----------
$pwSrc = Join-Path $extract "ms-playwright"
$pwDir = Join-Path $env:LOCALAPPDATA "ms-playwright"
if (Test-Path $pwSrc) {
    Say "安装浏览器内核到 $pwDir ..."
    New-Item -ItemType Directory -Force -Path $pwDir | Out-Null
    Get-ChildItem $pwSrc -Force | ForEach-Object {
        Copy-Item $_.FullName (Join-Path $pwDir $_.Name) -Recurse -Force
    }
    Say "浏览器内核: 已随包安装"
} else {
    Say "安装包内无浏览器内核, 在线下载(npmmirror 镜像, 约 3-8 分钟)..." "Yellow"
    $env:PLAYWRIGHT_DOWNLOAD_HOST = "https://npmmirror.com/mirrors/playwright"
    $ErrorActionPreference = "Continue"
    Invoke-Uv run python -m patchright install chromium 2>&1 | Select-Object -Last 2 | ForEach-Object { Write-Host $_ -ForegroundColor DarkGray }
    Invoke-Uv run python -m playwright install chromium 2>&1 | Select-Object -Last 2 | ForEach-Object { Write-Host $_ -ForegroundColor DarkGray }
    $ErrorActionPreference = "Stop"
    Remove-Item Env:PLAYWRIGHT_DOWNLOAD_HOST -ErrorAction SilentlyContinue
    Say "浏览器内核: 在线安装完成"
}

# ---------- 6. mpau 加入 PATH ----------
$venvScripts = Join-Path $InstallDir ".venv\Scripts"
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -notlike "*$venvScripts*") {
    [Environment]::SetEnvironmentVariable("Path", "$userPath;$venvScripts", "User")
    Say "已把 mpau 加入 PATH"
} else { Say "mpau 已在 PATH 中" }

# ---------- 7. 自检(启动本地 web 服务探活) ----------
Say "自检: 启动本地 web 服务验证..."
$env:MPAU_WEB_HOST = "127.0.0.1"
$env:MPAU_WEB_PORT = "8898"
$ErrorActionPreference = "Continue"
if ($uvMod) {
    $proc = Start-Process -FilePath $uvCmd -ArgumentList @("-m", "uv", "run", "python", "web/app.py") -WorkingDirectory $InstallDir -PassThru -WindowStyle Hidden
} else {
    $proc = Start-Process -FilePath $uvCmd -ArgumentList @("run", "python", "web/app.py") -WorkingDirectory $InstallDir -PassThru -WindowStyle Hidden
}
$ErrorActionPreference = "Stop"
$webOk = $false
for ($i = 0; $i -lt 30 -and -not $webOk; $i++) {
    Start-Sleep -Seconds 1
    try {
        $code = (Invoke-WebRequest -Uri "http://127.0.0.1:8898/" -UseBasicParsing -TimeoutSec 2).StatusCode
        if ($code -eq 200) { $webOk = $true }
    } catch { }
}
if ($proc -and -not $proc.HasExited) {
    & taskkill /PID $proc.Id /T /F 2>$null | Out-Null
}
Remove-Item Env:MPAU_WEB_HOST -ErrorAction SilentlyContinue
Remove-Item Env:MPAU_WEB_PORT -ErrorAction SilentlyContinue

# ---------- 8. 完成 ----------
Say ""
if ($webOk) {
    Say "==============================================" "Green"
    Say "  安装完成, 自检通过 ✔" "Green"
    Say "==============================================" "Green"
} else {
    Say "==============================================" "Red"
    Say "  安装完成, 但自检失败: web 后台 30 秒内未响应" "Red"
    Say "  请把 $InstallDir\logs\web-server.err.log 发给技术支持" "Red"
    Say "==============================================" "Red"
}

# ---------- 9. 生成启动器(双击即用) ----------
$vbsPath = Join-Path $InstallDir "web\open-mpau.vbs"
$vbs = @"
On Error Resume Next
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "$InstallDir"
sh.Run "cmd /c set PYTHONIOENCODING=utf-8 && set MPAU_WEB_HOST=127.0.0.1 && set MPAU_WEB_PORT=8898 && .venv\Scripts\python.exe web\app.py", 0, False
If WScript.Arguments.Count = 0 Then
  WScript.Sleep 2500
  ' Use a known browser directly (avoids "no application associated" errors)
  Set fso = CreateObject("Scripting.FileSystemObject")
  browser = ""
  For Each p In Array( _
    sh.ExpandEnvironmentStrings("%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"), _
    sh.ExpandEnvironmentStrings("%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"), _
    sh.ExpandEnvironmentStrings("%ProgramFiles%\Google\Chrome\Application\chrome.exe"), _
    sh.ExpandEnvironmentStrings("%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"), _
    sh.ExpandEnvironmentStrings("%LocalAppData%\Google\Chrome\Application\chrome.exe"), _
    sh.ExpandEnvironmentStrings("%ProgramFiles(x86)%\360\360se6\Application\360se.exe"), _
    sh.ExpandEnvironmentStrings("%ProgramFiles%\360\360se6\Application\360se.exe"), _
    sh.ExpandEnvironmentStrings("%ProgramFiles(x86)%\360\360Chrome\Chrome\Application\360chrome.exe"), _
    sh.ExpandEnvironmentStrings("%ProgramFiles%\360\360Chrome\Chrome\Application\360chrome.exe"), _
    sh.ExpandEnvironmentStrings("%LocalAppData%\360Chrome\Chrome\Application\360chrome.exe"), _
    sh.ExpandEnvironmentStrings("%AppData%\360Chrome\Chrome\Application\360chrome.exe"), _
    sh.ExpandEnvironmentStrings("%ProgramFiles(x86)%\Tencent\QQBrowser\QQBrowser.exe"), _
    sh.ExpandEnvironmentStrings("%ProgramFiles(x86)%\SogouExplorer\SogouExplorer.exe"), _
    sh.ExpandEnvironmentStrings("%ProgramFiles%\Mozilla Firefox\firefox.exe"), _
    sh.ExpandEnvironmentStrings("%ProgramFiles(x86)%\Mozilla Firefox\firefox.exe"), _
    sh.ExpandEnvironmentStrings("%LocalAppData%\CentBrowser\Application\chrome.exe"))
    If fso.FileExists(p) Then
      browser = p
      Exit For
    End If
  Next
  If browser <> "" Then
    sh.Run """" & browser & """ ""http://127.0.0.1:8898""", 1, False
  Else
    sh.Run "http://127.0.0.1:8898", 1, False
  End If
End If
"@
[System.IO.File]::WriteAllText($vbsPath, $vbs, [System.Text.Encoding]::ASCII)
Say "启动器已生成: $vbsPath"

# ---------- 10. 根目录中文启动入口(一眼能找到, 不藏子目录) ----------
$batPath = Join-Path $InstallDir "启动后台.bat"
$bat = @"
@echo off
chcp 65001 >nul
rem mpau web console launcher (root entry)
title mpau 发布后台
cd /d "%~dp0"
set MPAU_WEB_PORT=8898
netstat -ano | findstr ":%MPAU_WEB_PORT%" | findstr "LISTENING" >nul
if %errorlevel%==0 (
    echo 服务已在运行, 正在打开后台...
    start http://127.0.0.1:%MPAU_WEB_PORT%
    ping -n 3 127.0.0.1 >nul
    exit /b 0
)
set PYTHONIOENCODING=utf-8
set MPAU_WEB_HOST=127.0.0.1
echo 正在启动 mpau 发布后台: http://127.0.0.1:8898
echo 关闭本窗口即停止服务。
".venv\Scripts\python.exe" web/app.py
pause
"@
# bat 用 UTF-8(无BOM) + 开头 chcp 65001: 兼容默认936与已开UTF-8的两种环境
[System.IO.File]::WriteAllText($batPath, $bat, (New-Object System.Text.UTF8Encoding($false)))
Say "根目录启动入口: $batPath"

# ---------- 11. 桌面快捷方式 ----------
try {
    $ws = New-Object -ComObject WScript.Shell
    $lnkPath = Join-Path ([Environment]::GetFolderPath("Desktop")) "mpau 发布台.lnk"
    $lnk = $ws.CreateShortcut($lnkPath)
    $lnk.TargetPath = "$env:WINDIR\System32\wscript.exe"
    $lnk.Arguments = "`"$vbsPath`""
    $lnk.WorkingDirectory = $InstallDir
    $lnk.IconLocation = "$env:WINDIR\System32\shell32.dll,220"
    $lnk.Description = "mpau 多平台自动上传"
    $lnk.Save()
    Say "桌面快捷方式: mpau 发布台"
} catch {
    Say "桌面快捷方式创建失败(不影响使用): $_" "Yellow"
}

# ---------- 12. 开机自启(可选) ----------
$wantAuto = $false
if ($AutoStart) { $wantAuto = $true }
elseif (-not $NoAutoStart) {
    $ans = Read-Host "是否设置开机自动启动后台? (Y/N, 默认 N)"
    $wantAuto = ($ans -match "^[Yy]")
}
if ($wantAuto) {
    $taskName = "mpau-web"
    $tr = 'wscript.exe ""' + $vbsPath + '"" /nobrowser'
    & schtasks /create /tn $taskName /tr $tr /sc onlogon /rl limited /f 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Say "已设置开机自动启动(任务: $taskName)"
    } else {
        Say "开机自启设置失败, 可手动运行: schtasks /create /tn mpau-web /tr `"wscript.exe $vbsPath /nobrowser`" /sc onlogon /rl limited /f" "Yellow"
    }
}

# ---------- 13. 启动并打开后台 ----------
if (-not $SkipLaunch -and $webOk) {
    Say "正在启动后台服务..."
    & wscript.exe $vbsPath /nobrowser
    Start-Sleep -Seconds 2
    $opened = $false
    try { Start-Process "http://127.0.0.1:8898" -ErrorAction Stop; $opened = $true } catch { }
    if (-not $opened) {
        # 系统 http 关联缺失时, 尝试常见浏览器直接打开(含 360 等国内浏览器)
        $browser = @(
            "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
            "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
            "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
            "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
            "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe",
            "${env:ProgramFiles(x86)}\360\360se6\Application\360se.exe",
            "$env:ProgramFiles\360\360se6\Application\360se.exe",
            "${env:ProgramFiles(x86)}\360\360Chrome\Chrome\Application\360chrome.exe",
            "$env:ProgramFiles\360\360Chrome\Chrome\Application\360chrome.exe",
            "$env:LOCALAPPDATA\360Chrome\Chrome\Application\360chrome.exe",
            "$env:APPDATA\360Chrome\Chrome\Application\360chrome.exe",
            "${env:ProgramFiles(x86)}\Tencent\QQBrowser\QQBrowser.exe",
            "${env:ProgramFiles(x86)}\SogouExplorer\SogouExplorer.exe",
            "$env:ProgramFiles\Mozilla Firefox\firefox.exe",
            "${env:ProgramFiles(x86)}\Mozilla Firefox\firefox.exe",
            "$env:LOCALAPPDATA\CentBrowser\Application\chrome.exe"
        ) | Where-Object { Test-Path $_ } | Select-Object -First 1
        if ($browser) {
            Start-Process $browser "http://127.0.0.1:8898"
            $opened = $true
        }
    }
    if ($opened) {
        Say "后台已启动, 浏览器已打开 http://127.0.0.1:8898"
    } else {
        Say "后台已启动 ✔ 但本机缺少默认浏览器关联, 无法自动打开" "Yellow"
        Say "请手动打开浏览器访问: http://127.0.0.1:8898" "Yellow"
    }
} elseif (-not $webOk) {
    Say "自检未通过, 请先查看 $InstallDir\logs\web-server.err.log" "Yellow"
}

Say "下一步:"
Say "  1. 以后使用: 双击桌面「mpau 发布台」图标, 或双击 $InstallDir\启动后台.bat 即可打开后台"
Say "  2. 每个平台扫码登录一次自己的账号(在网页后台操作, 或命令 mpau <平台> login)"
Say "  3. 开始使用(批量发布 / 单条发布)"
Say ""
if (-not $wantAuto) {
    Say "提示: 如需开机自动启动, 重新运行安装器并加 -AutoStart 参数。" "DarkGray"
}
Say ""

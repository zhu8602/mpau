# mpau 环境诊断脚本: 定位 greenlet DLL 加载失败 / 托管 Python 回退等问题
# 用法: 双击同目录 诊断.bat, 或 powershell -ExecutionPolicy Bypass -File diagnose.ps1

$ErrorActionPreference = "Continue"

function Say($m, $c = "Cyan") { Write-Host $m -ForegroundColor $c }

Say ""
Say "========== mpau 安装环境诊断 =========="
$InstallDir = "D:\mpau-auto-upload"
Say "[1] 安装目录: $InstallDir -> $(if (Test-Path $InstallDir) { '存在' } else { '不存在(还没装成功)' })"

$py = Join-Path $InstallDir ".venv\Scripts\python.exe"
if (Test-Path $py) {
    $v = (& $py --version 2>&1) -join " "
    Say "[2] venv Python: $v"
    if ($v -match "3\.12") { Say "      (托管 Python, 自带运行库)" "Green" }
    else { Say "      (系统 Python, greenlet 失败通常=缺 VC++ 运行库)" "Yellow" }
    Say "[3] import greenlet, patchright:"
    & $py -c "import greenlet, patchright; print('     导入成功 OK')" 2>&1 | ForEach-Object { Say "      $_" }
} else {
    Say "[2] 未找到 venv (安装未完成)"
    Say "     $py"
}

Say "[4] 系统 VC++ 运行库检查:"
foreach ($dll in @("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll")) {
    $p = Join-Path $env:WINDIR "System32\$dll"
    Say "      $dll : $(if (Test-Path $p) { '存在' } else { '缺失!' })"
}

Say "[5] 托管 Python 下载源可达性 (npmmirror):"
try {
    $r = Invoke-WebRequest -Uri "https://registry.npmmirror.com/-/binary/python-build-standalone/" -Method Head -TimeoutSec 10 -UseBasicParsing
    Say "      可达 ($($r.StatusCode))"
} catch {
    Say "      不可达: $($_.Exception.Message)" "Yellow"
}

Say ""
Say "================================================"
Say "判断与处理:"
Say "  - [3] 显示导入成功 -> 环境正常, 登录失败另有原因"
Say "  - [3] 失败 且 [4] 有缺失 -> 安装微软运行库后重装:"
Say "      https://aka.ms/vs/17/release/vc_redist.x64.exe"
Say "  - [3] 失败 且 [4] 全部存在 -> 把本窗口完整内容发给技术支持"
Say "================================================"

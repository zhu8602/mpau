# 局域网模式启动脚本: 局域网内用户可通过 http://<本机IP>:8898 访问
# 用法: powershell -ExecutionPolicy Bypass -File web\start-lan.ps1
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$env:MPAU_WEB_HOST = "0.0.0.0"
$env:MPAU_WEB_PORT = "8898"

# 确保防火墙放行 8898 入站(需要管理员权限, 已有规则则跳过)
$rule = netsh advfirewall firewall show rule name="mpau-web-8898" 2>$null
if ($rule -notmatch "mpau-web-8898") {
    netsh advfirewall firewall add rule name="mpau-web-8898" dir=in action=allow protocol=TCP localport=8898
}

$ip = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254*" -and $_.InterfaceAlias -notmatch "vEthernet|Loopback|WSL|Hyper-V|VMware|VirtualBox" } |
    Select-Object -First 1 -ExpandProperty IPAddress)
if (-not $ip) { $ip = "本机IP" }

Write-Host "mpau Web 管理后台(局域网模式): http://$ip`:8898" -ForegroundColor Green
Write-Host "访问需要令牌: 完整入口链接(http://.../?token=...)见下方服务启动输出, 请勿外发" -ForegroundColor Yellow
Write-Host "Ctrl+C 停止服务"
uv run python web/app.py

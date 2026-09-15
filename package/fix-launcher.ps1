# 修复 mpau 启动器: 重新生成 open-mpau.vbs(新版逻辑: 支持 360 等浏览器, 不弹错误框)
# 用法: 把 修复.bat 与本文件放一起, 双击 修复.bat (或: powershell -ExecutionPolicy Bypass -File fix-launcher.ps1)
# 注意: 与 install.ps1 第 9 步的 vbs 模板保持一致, 改动需同步两处。

param(
    [string]$InstallDir = "D:\mpau-auto-upload"
)

$vbsPath = Join-Path $InstallDir "web\open-mpau.vbs"
if (-not (Test-Path $vbsPath)) {
    Write-Host "未找到 $vbsPath" -ForegroundColor Yellow
    Write-Host "如果安装目录不是 D:\mpau-auto-upload, 请用 -InstallDir 参数指定后重试。" -ForegroundColor Yellow
    exit 1
}

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
Write-Host ""
Write-Host "启动器已修复 ✔ ($vbsPath)" -ForegroundColor Green
Write-Host "正在启动后台并打开浏览器..."
& wscript.exe $vbsPath
Write-Host "如果浏览器没有自动打开, 请手动打开浏览器访问 http://127.0.0.1:8898" -ForegroundColor Yellow

<#
控制台启动管线：验证本地环境与构建产物，启动只监听本机的展示服务并打印访问地址。
后台进程隐藏窗口；研究进程不受影响，端口已监听时保留现有服务。
#>
param([int]$Port = 8001)
$ErrorActionPreference = 'Stop'
if ($Port -lt 1024 -or $Port -gt 65535) { throw '端口必须位于 1024 到 65535' }
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$PythonPath = Join-Path $ProjectRoot '.venv-research\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $PythonPath)) { throw '缺少 .venv-research 项目环境' }
if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot 'dist\index.html'))) { throw '请先在项目根目录运行 npm run build' }
$Listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($Listener) {
    Write-Output "端口 $Port 已有服务监听；未启动重复进程。"
} else {
    $OutputFolder = Join-Path $ProjectRoot 'artifacts'
    New-Item -ItemType Directory -Path $OutputFolder -Force | Out-Null
    $Process = Start-Process -FilePath $PythonPath -ArgumentList @('-m', 'uvicorn', 'dashboard_server:app', '--host', '127.0.0.1', '--port', $Port) -WorkingDirectory $ProjectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $OutputFolder 'dashboard-api.stdout.log') -RedirectStandardError (Join-Path $OutputFolder 'dashboard-api.stderr.log') -PassThru
    Write-Output "控制台服务已启动，进程 PID: $($Process.Id)"
}
Write-Output "浏览器访问：http://127.0.0.1:$Port"
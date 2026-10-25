$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root ".venv\Scripts\python.exe"
$port = 8503
$url = "http://127.0.0.1:$port"
$outLog = Join-Path $root "launcher.out.log"
$errLog = Join-Path $root "launcher.err.log"

function Test-Port {
    param([int]$Port)
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $client.Connect("127.0.0.1", $Port)
        $client.Close()
        return $true
    } catch {
        return $false
    }
}

if (-not (Test-Path $python)) {
    Write-Error "虚拟环境不存在：$python"
    exit 1
}

if (-not (Test-Port $port)) {
    Start-Process -FilePath $python `
        -ArgumentList @("-m", "streamlit", "run", "app.py", "--server.port", "$port", "--server.headless", "true") `
        -WorkingDirectory $root `
        -WindowStyle Hidden `
        -RedirectStandardOutput $outLog `
        -RedirectStandardError $errLog
}

$ready = $false
for ($i = 0; $i -lt 40; $i++) {
    if (Test-Port $port) {
        $ready = $true
        break
    }
    Start-Sleep -Milliseconds 500
}

if (-not $ready) {
    Start-Process notepad.exe $errLog
    exit 1
}

$chrome = "C:\Program Files\Google\Chrome\Application\chrome.exe"
if (Test-Path $chrome) {
    Start-Process -FilePath $chrome -ArgumentList $url
} else {
    Start-Process $url
}

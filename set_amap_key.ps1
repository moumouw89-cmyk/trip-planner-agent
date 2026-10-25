$ErrorActionPreference = "Stop"
$envPath = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) ".env"

Write-Host "Paste your Amap Web Service Key, then press Enter."
Write-Host "The key is hidden and will not be printed."
$secure = Read-Host "AMAP_API_KEY" -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
    $key = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
}

$key = $key.Trim()
if ($key.Length -lt 10) {
    Write-Host "Key is empty or too short. Nothing saved."
    Read-Host "Press Enter to close"
    exit 1
}

$lines = @()
if (Test-Path $envPath) {
    $lines = Get-Content -LiteralPath $envPath -Encoding UTF8
}
$found = $false
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match '^\s*AMAP_API_KEY\s*=') {
        $lines[$i] = "AMAP_API_KEY=$key"
        $found = $true
    }
}
if (-not $found) {
    $lines += "AMAP_API_KEY=$key"
}

$utf8 = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllLines($envPath, $lines, $utf8)
Write-Host "Saved to $envPath (length: $($key.Length)). Do not share this key."
Read-Host "Press Enter to close"

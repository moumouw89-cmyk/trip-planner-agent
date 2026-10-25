$ErrorActionPreference = "Stop"
$envPath = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) ".env"

Write-Host "Paste your DeepSeek API Key, then press Enter."
Write-Host "The key is hidden and will not be printed."
$secure = Read-Host "DEEPSEEK_API_KEY" -AsSecureString
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
$values = @{
    "OPENAI_API_KEY"  = $key
    "OPENAI_BASE_URL" = "https://api.deepseek.com/v1"
    "OPENAI_MODEL"    = "deepseek-chat"
}
foreach ($name in $values.Keys) {
    $found = $false
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match "^\s*$name\s*=") {
            $lines[$i] = "$name=$($values[$name])"
            $found = $true
        }
    }
    if (-not $found) {
        $lines += "$name=$($values[$name])"
    }
}

$utf8 = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllLines($envPath, $lines, $utf8)
Write-Host "Saved DeepSeek config to $envPath. Do not share this key."
Read-Host "Press Enter to close"

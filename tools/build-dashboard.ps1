# Build Knowledge Hub dashboard bundle from src\dashboard-chunks\01.js ... 10.js
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$src = Join-Path $root "src\dashboard-chunks"
$out = "D:\hermes agent\plugins\knowledge-hub\dashboard\dist\index.js"
$parts = 1..10 | ForEach-Object { Join-Path $src ("{0:D2}.js" -f $_) }
foreach ($p in $parts) {
  if (-not (Test-Path -LiteralPath $p)) { throw "missing chunk: $p" }
}
$sb = New-Object System.Text.StringBuilder
foreach ($p in $parts) {
  [void]$sb.AppendLine((Get-Content -LiteralPath $p -Raw -Encoding UTF8))
}
[System.IO.File]::WriteAllText($out, $sb.ToString(), (New-Object System.Text.UTF8Encoding($false)))
node --check $out
if ($LASTEXITCODE -ne 0) { throw "node --check failed" }
Write-Host "built: $out"
# Deploy the Knowledge Hub dashboard plugin into a Hermes Agent installation.
param(
  [string]$HermesHome = "D:\hermes agent"
)
$ErrorActionPreference = "Stop"
$src = Join-Path $PSScriptRoot "..\hermes-plugin"
$dst = Join-Path $HermesHome "plugins\knowledge-hub\dashboard"
if (-not (Test-Path -LiteralPath $src)) { throw "plugin source not found: $src" }
New-Item -ItemType Directory -Force -Path (Join-Path $dst "dist") | Out-Null
Copy-Item -LiteralPath (Join-Path $src "manifest.json") -Destination $dst -Force
Copy-Item -LiteralPath (Join-Path $src "plugin_api.py") -Destination $dst -Force
Copy-Item -LiteralPath (Join-Path $src "manual.html") -Destination $dst -Force
Copy-Item -LiteralPath (Join-Path $src "dist\index.js") -Destination (Join-Path $dst "dist") -Force
Copy-Item -LiteralPath (Join-Path $src "dist\style.css") -Destination (Join-Path $dst "dist") -Force
Write-Host "deployed: $dst"
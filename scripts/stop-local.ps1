<#
.SYNOPSIS
  Stops what start-local.ps1 started: the API, the worker and the web; with -Services also the Docker services
  (their data stays in the Docker volumes).

.EXAMPLE
  .\scripts\stop-local.ps1
  .\scripts\stop-local.ps1 -Services
#>
[CmdletBinding()]
param([switch]$Services)

$Root = Split-Path -Parent $PSScriptRoot
$Pids = Join-Path $Root '.local\pids'

foreach ($name in @('web', 'worker', 'api')) {
  $pidFile = Join-Path $Pids "$name.pid"
  if (-not (Test-Path $pidFile)) { continue }
  $id = Get-Content $pidFile
  if (Get-Process -Id $id -ErrorAction SilentlyContinue) {
    # The whole tree: cmd.exe started uv, uv started python (or pnpm started vite).
    taskkill /PID $id /T /F *> $null
    Write-Host "Stopped $name (pid $id)"
  }
  Remove-Item $pidFile -Force
}

if ($Services) {
  Push-Location $Root
  try { docker compose -f infra/docker-compose/compose.yaml stop } finally { Pop-Location }
}

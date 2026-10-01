<#
.SYNOPSIS
  Shows whether the local platform is up: Docker services, the API, the worker and the web.
#>
$Root = Split-Path -Parent $PSScriptRoot
$Pids = Join-Path $Root '.local\pids'

function Test-Url([string]$Url) {
  try { (Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3).StatusCode -lt 500 } catch { $false }
}

Push-Location $Root
try { docker compose -f infra/docker-compose/compose.yaml ps --format 'table {{.Service}}\t{{.Status}}' } finally { Pop-Location }

Write-Host ''
foreach ($name in @('api', 'worker', 'web')) {
  $pidFile = Join-Path $Pids "$name.pid"
  $state = 'stopped'
  if (Test-Path $pidFile) {
    $id = Get-Content $pidFile
    if (Get-Process -Id $id -ErrorAction SilentlyContinue) { $state = "running (pid $id)" }
  }
  Write-Host ("{0,-8} {1}" -f $name, $state)
}
Write-Host ''
Write-Host ("API health: {0}" -f $(if (Test-Url 'http://127.0.0.1:8100/api/v1/health/ready') { 'ready' } else { 'not ready' }))
Write-Host ("Web:        {0}" -f $(if (Test-Url 'http://localhost:5173') { 'http://localhost:5173' } else { 'not answering' }))

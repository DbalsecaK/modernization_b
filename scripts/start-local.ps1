<#
.SYNOPSIS
  Starts the whole platform on this machine (plan P1): Docker services, configuration, database, development data,
  sandbox images, API, worker and web. Optionally reproduces the demo projects from the recordings (no model cost).

.EXAMPLE
  .\scripts\start-local.ps1            # start everything
  .\scripts\start-local.ps1 -Demo      # ... and the three demo projects (first time: several minutes)
  .\scripts\start-local.ps1 -Sync      # ... after a pull: Python and Node dependencies again

.NOTES
  Logs and process ids go to .local\ (git-ignored). Stop with .\scripts\stop-local.ps1.
  Development only: dev-auth is on, demo data replays recordings, nothing here is meant for a server.
#>
[CmdletBinding()]
param(
  [switch]$Demo,
  [switch]$Sync,
  [switch]$SkipImages
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Local = Join-Path $Root '.local'
$Logs = Join-Path $Local 'logs'
$Pids = Join-Path $Local 'pids'
New-Item -ItemType Directory -Force $Logs, $Pids | Out-Null
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'

function Step([string]$Text) { Write-Host "`n==> $Text" -ForegroundColor Cyan }
function Done([string]$Text) { Write-Host "    $Text" -ForegroundColor Green }
function Fail([string]$Text) { Write-Host "    $Text" -ForegroundColor Red; exit 1 }

function Find-Uv {
  $found = Get-Command uv -ErrorAction SilentlyContinue
  if ($found) { return $found.Source }
  foreach ($candidate in @("$env:APPDATA\Python\Python312\Scripts\uv.exe", "$env:USERPROFILE\.local\bin\uv.exe")) {
    if (Test-Path $candidate) { return $candidate }
  }
  return $null
}

function Invoke-Checked([string]$File, [string[]]$Arguments) {
  & $File @Arguments
  if ($LASTEXITCODE -ne 0) { Fail "$File $($Arguments -join ' ') failed (exit $LASTEXITCODE)" }
}

function Test-Url([string]$Url) {
  try { (Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3).StatusCode -lt 500 } catch { $false }
}

function Wait-Url([string]$Name, [string]$Url, [int]$Seconds) {
  for ($i = 0; $i -lt $Seconds; $i += 2) {
    if (Test-Url $Url) { Done "$Name ready ($Url)"; return }
    Start-Sleep -Seconds 2
  }
  Fail "$Name did not answer at $Url in $Seconds s; see $Logs"
}

function Start-Background([string]$Name, [string]$Command) {
  $pidFile = Join-Path $Pids "$Name.pid"
  if (Test-Path $pidFile) {
    $old = Get-Content $pidFile
    if (Get-Process -Id $old -ErrorAction SilentlyContinue) { Done "$Name already running (pid $old)"; return }
  }
  $out = Join-Path $Logs "$Name.log"
  $err = Join-Path $Logs "$Name.err.log"
  $process = Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', $Command -WorkingDirectory $Root `
    -RedirectStandardOutput $out -RedirectStandardError $err -WindowStyle Hidden -PassThru
  Set-Content -Path $pidFile -Value $process.Id
  Done "$Name started (pid $($process.Id), log .local\logs\$Name.log)"
}

Step 'Checking the tools'
$Uv = Find-Uv
foreach ($tool in @(@('docker', (Get-Command docker -ErrorAction SilentlyContinue)), @('node', (Get-Command node -ErrorAction SilentlyContinue)),
                    @('pnpm', (Get-Command pnpm -ErrorAction SilentlyContinue)), @('uv', $Uv))) {
  if (-not $tool[1]) { Fail "$($tool[0]) not found: see the requirements in docs\GUIA_PRUEBA_LOCAL.md" }
}
docker info --format '{{.ServerVersion}}' *> $null
if ($LASTEXITCODE -ne 0) { Fail 'Docker is not running: start Docker Desktop and try again' }
Done "docker, node, pnpm and uv found"

Step 'Configuration (.env files; existing values are kept)'
Push-Location $Root
try {
  Invoke-Checked 'python' @('infra/docker-compose/init_env.py')

  Step 'Docker services (PostgreSQL, Keycloak, OpenFGA, OpenBao, MinIO, Neo4j, Redis, ClamAV, Mailpit)'
  Invoke-Checked 'docker' @('compose', '-f', 'infra/docker-compose/compose.yaml', 'up', '-d', '--wait')
  Done 'services healthy'

  if ($Sync -or -not (Test-Path (Join-Path $Root '.venv'))) {
    Step 'Python dependencies (uv sync)'
    $env:UV_LINK_MODE = 'copy'
    Invoke-Checked $Uv @('sync', '--all-packages')
  }
  if ($Sync -or -not (Test-Path (Join-Path $Root 'node_modules'))) {
    Step 'Node dependencies (pnpm install)'
    Invoke-Checked 'pnpm' @('install')
  }

  Step 'Database: migrations and development data'
  Invoke-Checked $Uv @('run', '--no-sync', 'alembic', '-c', 'apps/api/alembic.ini', 'upgrade', 'head')
  Invoke-Checked $Uv @('run', '--no-sync', 'python', '-m', 'nexti_api.cli', 'seed-dev')

  if (-not $SkipImages) {
    Step 'Sandbox images (built once; a few minutes the first time)'
    $images = @(
      @('nexti-sandbox-java:2', @('build', '-q', '-t', 'nexti-sandbox-java:2', 'infra/sandbox/java')),
      @('nexti-sandbox-web:1', @('build', '-q', '-f', 'infra/sandbox/web/Dockerfile', '-t', 'nexti-sandbox-web:1', '.')),
      @('nexti-sandbox-frontend:1', @('build', '-q', '-f', 'infra/sandbox/frontend/Dockerfile', '-t', 'nexti-sandbox-frontend:1', '.')),
      @('nexti-sandbox-dotnet:1', @('build', '-q', '-t', 'nexti-sandbox-dotnet:1', 'infra/sandbox/dotnet'))
    )
    foreach ($image in $images) {
      docker image inspect $image[0] *> $null
      if ($LASTEXITCODE -eq 0) { Done "$($image[0]) present"; continue }
      Write-Host "    building $($image[0])..."
      Invoke-Checked 'docker' $image[1]
      Done "$($image[0]) built"
    }
  }

  if ($Demo) {
    # Before the worker starts: the demo runs the pipeline in its own process.
    Step 'Demo projects, reproduced from the recordings (no model cost; existing ones are kept)'
    $workerPid = Join-Path $Pids 'worker.pid'
    if ((Test-Path $workerPid) -and (Get-Process -Id (Get-Content $workerPid) -ErrorAction SilentlyContinue)) {
      taskkill /PID (Get-Content $workerPid) /T /F *> $null
      Remove-Item $workerPid -Force
      Done 'worker stopped while the demo runs'
      Start-Sleep -Seconds 35  # its heartbeat must go stale
    }
    Invoke-Checked $Uv @('run', '--no-sync', 'python', 'tools/demo/clean.py')
    Invoke-Checked $Uv @('run', '--no-sync', 'python', 'tools/demo/seed_demo.py')
    Invoke-Checked $Uv @('run', '--no-sync', 'python', 'tools/demo/inputs.py')
  }

  Step 'API, worker and web'
  Start-Background 'api' "`"$Uv`" run --no-sync uvicorn --factory nexti_api.main:create_app --host 127.0.0.1 --port 8100"
  Start-Background 'worker' "`"$Uv`" run --no-sync python -m nexti_worker"
  Start-Background 'web' 'pnpm --filter @nexti/web dev --port 5173 --strictPort'
  Wait-Url 'API' 'http://127.0.0.1:8100/api/v1/health/live' 120
  Wait-Url 'Web' 'http://localhost:5173' 120
}
finally {
  Pop-Location
}

Write-Host ''
Write-Host 'The platform is running.' -ForegroundColor Green
Write-Host '  Web:    http://localhost:5173  (sign in with "dev-auth": María Torres, Luis Andrade or Platform Admin)'
Write-Host '  API:    http://127.0.0.1:8100/api/v1/docs'
Write-Host '  Mail:   http://localhost:8025  (invitations)'
Write-Host '  Logs:   .local\logs\    Status: .\scripts\status-local.ps1    Stop: .\scripts\stop-local.ps1'
Write-Host '  Guide:  docs\GUIA_PRUEBA_LOCAL.md'

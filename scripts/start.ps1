[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$BackendPort = 8000,
    [ValidateRange(1, 65535)]
    [int]$FrontendPort = 3000
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$RuntimeDir = Join-Path $ProjectRoot "data\runtime"
$LogDir = Join-Path $ProjectRoot "data\logs"
$BackendPidFile = Join-Path $RuntimeDir "backend.json"
$FrontendPidFile = Join-Path $RuntimeDir "frontend.json"
function Test-PortAvailable([int]$Port) {
    return -not (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
}

function Wait-Http([string]$Url, [int]$TimeoutSeconds = 45) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 3
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                return
            }
        } catch {}
        Start-Sleep -Seconds 1
    }
    throw "Timed out waiting for $Url"
}

function Save-ProcessRecord([string]$Path, [System.Diagnostics.Process]$Process) {
    @{
        pid = $Process.Id
        start_file_time = $Process.StartTime.ToFileTimeUtc()
    } | ConvertTo-Json | Set-Content -LiteralPath $Path -Encoding utf8
}

if (-not (Test-Path (Join-Path $ProjectRoot ".venv\Scripts\Activate.ps1"))) {
    throw "Missing .venv. Create the uv environment before starting the project."
}
foreach ($command in @("docker", "npm")) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "Missing required command: $command"
    }
}
foreach ($port in @($BackendPort, $FrontendPort)) {
    if (-not (Test-PortAvailable $port)) {
        throw "Port $port is already in use. Stop that service first; this script will not terminate unrelated processes."
    }
}

New-Item -ItemType Directory -Path $RuntimeDir, $LogDir -Force | Out-Null
Remove-Item -LiteralPath $BackendPidFile, $FrontendPidFile -Force -ErrorAction SilentlyContinue

Push-Location $ProjectRoot
try {
    & docker compose up -d postgres
    if ($LASTEXITCODE -ne 0) { throw "Could not start the project PostgreSQL service." }
    $databaseReady = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        & docker compose exec -T postgres pg_isready | Out-Null
        if ($LASTEXITCODE -eq 0) {
            $databaseReady = $true
            break
        }
        Start-Sleep -Seconds 1
    }
    if (-not $databaseReady) { throw "PostgreSQL did not become ready." }
} finally {
    Pop-Location
}

$backendLog = Join-Path $LogDir "backend.log"
$frontendLog = Join-Path $LogDir "frontend.log"
$activate = Join-Path $ProjectRoot ".venv\Scripts\Activate.ps1"
$backendDir = Join-Path $ProjectRoot "backend"
$frontendDir = Join-Path $ProjectRoot "frontend"
$backendCommand = "Set-Location '$backendDir'; . '$activate'; `$env:PORT = '$BackendPort'; `$env:CORS_ORIGINS = 'http://localhost:$FrontendPort,http://127.0.0.1:$FrontendPort'; python main.py *>> '$backendLog'"
$frontendCommand = "Set-Location '$frontendDir'; `$env:VITE_API_PROXY_TARGET = 'http://127.0.0.1:$BackendPort'; npm run dev -- --host 127.0.0.1 --port $FrontendPort *>> '$frontendLog'"

$backend = Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $backendCommand) -WindowStyle Hidden -PassThru
$frontend = $null
try {
    Wait-Http "http://127.0.0.1:$BackendPort/docs"
    Save-ProcessRecord $BackendPidFile $backend
    $frontend = Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $frontendCommand) -WindowStyle Hidden -PassThru
    Wait-Http "http://127.0.0.1:$FrontendPort"
    Save-ProcessRecord $FrontendPidFile $frontend
} catch {
    foreach ($process in @($frontend, $backend)) {
        if ($null -ne $process -and -not $process.HasExited) {
            & taskkill.exe /PID $process.Id /T /F | Out-Null
        }
    }
    Remove-Item -LiteralPath $BackendPidFile, $FrontendPidFile -Force -ErrorAction SilentlyContinue
    throw
}

Write-Host "Project started: http://127.0.0.1:$FrontendPort"
Write-Host "Backend docs:    http://127.0.0.1:$BackendPort/docs"
Write-Host "Logs:            $LogDir"

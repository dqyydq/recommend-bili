[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$RuntimeDir = Join-Path $ProjectRoot "data\runtime"

function Stop-RecordedProcess([string]$Name) {
    $path = Join-Path $RuntimeDir "$Name.json"
    if (-not (Test-Path $path)) { return }
    try {
        $record = Get-Content -Raw -LiteralPath $path | ConvertFrom-Json
        $process = Get-Process -Id ([int]$record.pid) -ErrorAction Stop
        if ($process.StartTime.ToFileTimeUtc() -eq [int64]$record.start_file_time) {
            & taskkill.exe /PID $process.Id /T /F | Out-Null
            if ($LASTEXITCODE -ne 0) { throw "taskkill failed with exit code $LASTEXITCODE" }
            Write-Host "Stopped $Name process tree rooted at $($process.Id)."
        } else {
            Write-Warning "Skipped $Name PID $($record.pid): it no longer matches the recorded process."
        }
    } catch {
        Write-Warning "Could not stop recorded $Name process: $($_.Exception.Message)"
    } finally {
        Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
    }
}

Stop-RecordedProcess "frontend"
Stop-RecordedProcess "backend"

Push-Location $ProjectRoot
try {
    & docker compose down
    if ($LASTEXITCODE -ne 0) { throw "Could not stop the project Docker Compose services." }
} finally {
    Pop-Location
}

Write-Host "Project services stopped. PostgreSQL data volume was preserved."

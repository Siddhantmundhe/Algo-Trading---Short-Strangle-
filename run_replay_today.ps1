param(
    [ValidateSet("NIFTY", "BANKNIFTY")]
    [string]$Index = "NIFTY",

    [string]$Date = "",

    [int]$StrikeBufferPoints = 1000,

    [int]$ActiveExpiryCount = 3,

    [int]$MaxContracts = 0
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $pythonExe)) {
    throw "Python executable not found at $pythonExe"
}

$configPath = if ($Index -eq "BANKNIFTY") {
    "configs\live\strangle_live_banknifty_top2.json"
} else {
    "configs\live\strangle_live_top2.json"
}

$args = @(
    "scripts\replay_from_fetched_data.py"
    "--config", $configPath
    "--strike-buffer-points", $StrikeBufferPoints
    "--active-expiry-count", $ActiveExpiryCount
    "--max-contracts", $MaxContracts
)

if ($Date) {
    $args += @("--date", $Date)
}

& $pythonExe @args

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root '.venv\Scripts\python.exe'

if (!(Test-Path $python)) {
    throw "Python not found at $python"
}

$confirm = 'YES_LIVE'

function Start-Runner {
    param(
        [string]$Title,
        [string]$Command
    )

    Start-Process powershell -ArgumentList @(
        '-NoExit',
        '-Command',
        "cd '$root'; `$Host.UI.RawUI.WindowTitle = '$Title'; $Command"
    ) | Out-Null
}

Start-Runner -Title 'Strangle NIFTY LIVE' -Command "& '$python' '.\\scripts\\live_strangle_runner.py' --config '.\\configs\\live\\strangle_live_nifty_orders_v1.json' --mode live --confirm-live $confirm"
Start-Runner -Title 'Strangle BANKNIFTY LIVE' -Command "& '$python' '.\\scripts\\live_strangle_runner.py' --config '.\\configs\\live\\strangle_live_banknifty_orders_v1.json' --mode live --confirm-live $confirm"

Write-Host 'Launched NIFTY and BANKNIFTY strangle LIVE runners in separate terminals.'
Write-Host 'Warning: This places real orders.'

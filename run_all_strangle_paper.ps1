$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root '.venv\Scripts\python.exe'

if (!(Test-Path $python)) {
    throw "Python not found at $python"
}

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

Start-Runner -Title 'Strangle NIFTY Paper' -Command "& '$python' '.\\scripts\\live_strangle_paper.py' --config '.\\configs\\live\\strangle_live_top2.json'"
Start-Runner -Title 'Strangle BANKNIFTY Paper' -Command "& '$python' '.\\scripts\\live_strangle_paper.py' --config '.\\configs\\live\\strangle_live_banknifty_top2.json'"

Write-Host 'Launched strangle paper runners in separate terminals.'

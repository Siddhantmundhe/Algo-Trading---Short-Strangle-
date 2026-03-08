# Daily Workflow

## Goal
Run the strategy safely in the morning, and keep a repeatable path to replay the same session later from saved candles.

## Start Of Day
1. Activate the repo virtual environment.
2. Refresh the Kite token if required.
3. Run auth and pre-open checks.
4. Decide whether the session is paper-only or live.

## Paper Or Live Commands
```powershell
python scripts\live_strangle_paper.py --config configs\live\strangle_live_top2.json
python scripts\live_strangle_paper.py --config configs\live\strangle_live_banknifty_top2.json
python scripts\live_strangle_runner.py --config configs\live\strangle_live_nifty_orders_v1.json --mode live --confirm-live YES_LIVE
python scripts\live_strangle_runner.py --config configs\live\strangle_live_banknifty_orders_v1.json --mode live --confirm-live YES_LIVE
```

## Replay A Session From Stored Data
Use this path if you want to reconstruct a day without depending on the paper runner logs.

```powershell
.\run_replay_today.ps1
.\run_replay_today.ps1 -Index BANKNIFTY
.\run_replay_today.ps1 -Date 2026-03-06
```

This flow:
- fetches one session of underlying and options candles from Kite
- merges the session into local `data/*.csv`
- replays the selected date using the live strategy config

## End Of Day
1. Review output under `reports/nifty/live/`, `reports/banknifty/live/`, and `reports/replay/`.
2. Note auth issues, order errors, stop hits, and unusual market conditions.
3. Carry forward only action items that change the next session's risk or execution.

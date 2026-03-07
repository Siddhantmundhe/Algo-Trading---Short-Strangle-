# Live Runbook

## Pre-open (daily)
1. Activate venv.
2. Refresh token (`broker/generate_kite_token.py`).
3. Auth check (`broker/check_kite_auth.py`).
4. Run pre-open checks for both live configs.
5. Confirm no stale `STOP_TRADING.txt`.

## Paper run commands
```powershell
python scripts\live_strangle_paper.py --config configs\live\strangle_live_top2.json
python scripts\live_strangle_paper.py --config configs\live\strangle_live_banknifty_top2.json
```

## Live run commands
```powershell
python scripts\pre_open_healthcheck.py --config configs\live\strangle_live_nifty_orders_v1.json
python scripts\pre_open_healthcheck.py --config configs\live\strangle_live_banknifty_orders_v1.json
python scripts\live_strangle_runner.py --config configs\live\strangle_live_nifty_orders_v1.json --mode live --confirm-live YES_LIVE
python scripts\live_strangle_runner.py --config configs\live\strangle_live_banknifty_orders_v1.json --mode live --confirm-live YES_LIVE
```

## Intraday monitoring
- Watch auth/session errors.
- Watch order rejection and symbol resolution logs.
- If abnormal behavior: trigger kill-switch and stop runners.

## Post-close
- Verify trade CSV generated in `reports/nifty/live/` and `reports/banknifty/live/`.
- Summarize net PnL and stop-hit reason.
- Log next-day action items.

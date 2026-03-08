# Nifty Options Lab

Research repo for NIFTY and BANKNIFTY short-strangle research with backtesting, sweeps, and paper-live runners.

## Scope (v1)
- Strategy family: short strangle (premium-target strikes)
- Index: NIFTY, BANKNIFTY
- Backtest style: intraday, portfolio-level PnL with costs
- Outputs: ranked variants by return + drawdown quality

## Daily Operator Flow
- Refresh Kite token and verify auth before market use.
- Run pre-open checks before paper or live execution.
- Use `run_replay_today.ps1` to fetch a day of candles and replay the live config from stored data.
- Review generated trade CSVs under `reports/`.

## Layout
- `data/`: cached historical datasets
- `configs/backtest/`: backtest configs
- `configs/sweep/`: sweep configs
- `configs/live/`: paper and real-live runner configs
- `docs/`: strategy spec, risk controls, methodology, live runbook
- `src/engine/`: simulation engine
- `src/strategies/`: strategy definitions
- `src/analytics/`: metrics and report helpers
- `scripts/`: runnable entry points
- `reports/nifty/`: NIFTY results (`backtests`, `sweeps`, `live`)
- `reports/banknifty/`: BANKNIFTY results (`backtests`, `sweeps`, `live`)
- `reports/comparisons/`: side-by-side method comparisons

## Quickstart
```powershell
py -3.9 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python scripts\run_backtest.py --config configs\backtest\strangle_v1.json
python scripts\run_backtest.py --config configs\backtest\strangle_banknifty_live_best_risk.json
python scripts\run_sweep.py --config configs\sweep\strangle_sweep_v1.json
python scripts\run_sweep.py --config configs\sweep\strangle_sweep_banknifty_delta_v1.json --sample-random 120 --seed 42
python scripts\live_strangle_paper.py --config configs\live\strangle_live_top2.json
python scripts\live_strangle_paper.py --config configs\live\strangle_live_banknifty_top2.json
python scripts\pre_open_healthcheck.py --config configs\live\strangle_live_nifty_orders_v1.json
python scripts\pre_open_healthcheck.py --config configs\live\strangle_live_banknifty_orders_v1.json
python scripts\live_strangle_runner.py --config configs\live\strangle_live_nifty_orders_v1.json --mode live --confirm-live YES_LIVE
python scripts\live_strangle_runner.py --config configs\live\strangle_live_banknifty_orders_v1.json --mode live --confirm-live YES_LIVE
.\run_replay_today.ps1
.\run_replay_today.ps1 -Index BANKNIFTY
.\run_replay_today.ps1 -Date 2026-03-06
```

## Replay Workflow
Use the replay flow when you want to reconstruct a session from stored candles without having run the paper strategy live that morning.

```powershell
.\run_replay_today.ps1
python scripts\replay_from_fetched_data.py --config configs\live\strangle_live_top2.json --date 2026-03-06
python scripts\session_replay.py --config configs\live\strangle_live_top2.json --date 2026-03-06
```

What each command does:
- `run_replay_today.ps1`: fetches one session of candles, stores them into local `data/*.csv`, then replays that date.
- `replay_from_fetched_data.py`: Python entry point behind the PowerShell wrapper.
- `session_replay.py`: replays a day that already exists in local data.

## Required Data
Backtest expects two CSV files:

1. `data/underlying_5m.csv`
Required columns:
- `datetime` (or `date` / `timestamp` / `time`)
- `open`, `high`, `low`, `close`

2. `data/options_5m.csv`
Required columns:
- `datetime` (or `date` / `timestamp` / `time`)
- `expiry`
- `strike`
- `option_type` (or `instrument_type`) with values `CE` / `PE`
- `open`, `high`, `low`, `close`
Optional columns:
- `symbol` (or `tradingsymbol`)
- `delta` (used directly for `delta_target` method if available; otherwise a proxy is used)

## Strike Methods
- `premium_target`: selects CE/PE with premium near target band.
- `fixed_distance`: selects strikes at ATM +/- fixed points.
- `delta_target`: selects strikes nearest target delta (real delta column if available, else proxy).

## Notes
- This repo is research-first. Paper/live execution comes after robust out-of-sample validation.
- `live_strangle_runner.py` places real orders in `--mode live`.
- Live safety controls in config: `max_daily_loss_rupees`, `max_consecutive_losses`, `live_require_confirm`.
- Do not commit API secrets or tokens.

## Documentation Pack
- `docs/01_strategy_spec.md`
- `docs/02_data_contract.md`
- `docs/03_backtest_methodology.md`
- `docs/04_risk_controls.md`
- `docs/05_live_runbook.md`
- `docs/06_post_trade_review.md`
- `docs/07_results_summary.md`
- `docs/08_known_limits.md`
- `docs/09_daily_workflow.md`

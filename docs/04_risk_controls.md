# Risk Controls

## Hard controls in configs
- `max_daily_loss_rupees`
- `max_consecutive_losses` (live order configs)
- `max_trades_per_day`
- `combined_mtm_sl_rupees`
- `combined_mtm_target_rupees`
- `per_leg_sl_pct`
- `entry_time` + `exit_time` + market time bounds

## NIFTY baseline
- Daily loss cap: `₹3000`
- Combined SL: `₹2000`
- Combined target: `₹1500`
- Per-leg SL: `30%`

## BANKNIFTY baseline
- Daily loss cap: `₹5000`
- Combined SL: `₹3500`
- Combined target: `₹2500`
- Per-leg SL: `35%`

## Operational controls
- Live requires explicit phrase (`YES_LIVE`) in order runner.
- Use pre-open healthcheck before any live session.
- Keep `STOP_TRADING.txt` as emergency kill-switch.

## Escalation policy
- After 2 consecutive losing sessions, do not widen stops.
- Freeze deployment and re-run replay/backtest with latest data.
- Resume only after configuration review and documented rationale.

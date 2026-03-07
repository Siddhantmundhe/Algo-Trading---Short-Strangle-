# Results Summary

## NIFTY backtest snapshot (from `reports/nifty/backtests/final_top5_summary.csv`)
- Top2 (live-like baseline):
  - Trades: `27`
  - Net PnL: `₹21,515.75`
  - Max Drawdown: `-₹3,233.00`
  - Win Rate: `74.07%`
  - Profit Factor: `2.30`
- Top3 (aggressive):
  - Net PnL: `₹27,321.25`
  - Max Drawdown: `-₹4,457.50`
  - Win Rate: `70.37%`
  - Profit Factor: `2.90`

## Method comparison (NIFTY)
From `reports/comparisons/compare_delta_vs_premium.csv`:
- `delta_target_015`: Net `₹21,515.75`, PF `2.30`
- `premium_target_60`: Net `-₹644.00`, PF `0.94`

Inference:
- Delta-target currently dominates premium-target in the tested sample.

## BANKNIFTY sweep snapshot
From `reports/banknifty/sweeps/banknifty_sweep_top20_sample120.json` top result:
- Trades: `31`
- Net PnL: `₹26,560.50`
- Max Drawdown: `-₹6,058.50`
- Win Rate: `80.65%`
- Profit Factor: `3.33`

## Replay caveat
Session replay for `2026-03-02` produced loss on both indices in the checked run; strategy remains regime-sensitive and must be monitored with day filters and strict risk caps.

## Deployment stance
- Continue paper-forward as primary validation.
- Promote to live only with unchanged config, logged controls, and daily review discipline.

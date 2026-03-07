# Backtest Methodology

## Engine setup
- Entry/exit and strike selection are config-driven JSON files.
- One strangle/day baseline (`max_trades_per_day = 1`).
- Costs included:
  - Per-order slippage
  - Roundtrip charges per lot

## Parameter research process
- Deterministic backtests via:
  - `scripts/run_backtest.py --config <...>`
- Randomized sweeps via:
  - `scripts/run_sweep.py --config <...> --sample-random N --seed S`
- Current usage includes 120-sample random sweeps for BANKNIFTY.

## In-sample vs out-of-sample policy
- Current repository has strong sweep/backtest outputs but no explicit enforced walk-forward split file yet.
- Practical policy to follow:
  - Use first block for tuning.
  - Freeze params.
  - Validate on later block with no retuning.

## Selection principle
- Select variants on multi-metric quality, not net PnL only:
  - max drawdown
  - profit factor
  - win rate
  - consistency across nearby parameter sets

## Known modeling limitations
- No market-impact model.
- Fill model is simplified to candle/price logic plus flat slippage.
- Delta-target quality depends on whether real option delta column exists.

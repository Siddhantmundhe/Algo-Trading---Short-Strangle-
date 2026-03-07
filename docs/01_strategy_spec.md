# Strategy Spec

## Objective
Capture intraday theta decay via one short strangle per day on index weekly options, with strict loss caps and forced same-day exit.

## Instruments
- Index: `NIFTY`, `BANKNIFTY`
- Underlying signal clock: 5-minute series
- Trade instruments: weekly CE + PE (one short each)

## Current live baseline (paper/live configs)
- Entry time: `09:20`
- Exit time: `15:20` (intraday only, no overnight carry)
- Max trades/day: `1`
- Strike method: `delta_target`
- NIFTY: CE delta `0.15`, PE delta `-0.15`, lot size `65`
- BANKNIFTY: CE delta `0.15`, PE delta `-0.15`, lot size `30`

## Exit and risk logic
- Per-leg stop:
  - NIFTY `30%`
  - BANKNIFTY `35%`
- Combined MTM SL:
  - NIFTY `₹2000`
  - BANKNIFTY `₹3500`
- Combined MTM target:
  - NIFTY `₹1500`
  - BANKNIFTY `₹2500`
- Daily loss cap:
  - NIFTY `₹3000`
  - BANKNIFTY `₹5000`
- Max consecutive losses (live orders configs): `2`

## Position sizing
- Default: `lots = 1`
- Exposure is config-driven; runner does not auto-scale lots from capital.

## Edge hypothesis
- On most non-trending sessions, OTM option decay + IV mean behavior should outperform paid transaction costs.
- Risk controls are designed to truncate trend-day tail losses.

## Invalidation conditions
- Repeated negative expectancy out-of-sample for latest 8-12 weeks.
- Profit factor below 1 over rolling recent sample.
- Drawdown breach beyond pre-accepted risk budget.

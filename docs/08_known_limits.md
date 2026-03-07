# Known Limits

## Modeling limits
- Simplified execution model with flat slippage assumptions.
- No explicit queue-position or market-impact modeling.
- Delta-target behavior can degrade when true delta column is unavailable.

## Market/regime limits
- Trend days and gap days can break short-strangle payoff symmetry.
- Event days (RBI/Fed/budget/global shock) can trigger outsized losses.
- Weekly expiry behavior is non-stationary across months.

## Data limits
- Backtest quality depends on options chain completeness near selected strikes.
- Missing candles around entry/exit can bias outcomes.

## Operational limits
- Daily token/auth dependency can block runs.
- Local machine uptime/network quality affects live runners.
- Manual oversight still required for exceptional events.

## Risk reminder
- This is a short-vol strategy with fat-tail risk.
- Win rate alone is not sufficient; drawdown and left-tail control are critical.

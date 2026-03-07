# Data Contract

## Required datasets
- `data/underlying_5m.csv` (or banknifty equivalent file used by config)
- `data/options_5m.csv` (or banknifty equivalent file used by config)

## Underlying schema
- Required columns:
  - `datetime` (or alias: `date`, `timestamp`, `time`)
  - `open`, `high`, `low`, `close`

## Options schema
- Required columns:
  - `datetime` (or alias: `date`, `timestamp`, `time`)
  - `expiry`
  - `strike`
  - `option_type` or `instrument_type` (`CE` / `PE`)
  - `open`, `high`, `low`, `close`
- Optional columns:
  - `symbol`/`tradingsymbol`
  - `delta` (if missing, engine uses proxy for delta-target selection)

## Time and session assumptions
- Timezone: India market session
- Candle frame: 5-minute
- Strategy session window: 09:20 to 15:20; market bounds 09:15 to 15:30

## Data quality checks before run
- No duplicate timestamps for same instrument.
- No missing `close` on tradeable bars.
- Correct option type values (`CE`/`PE` only).
- Expiry parsable and aligned to weekly cycle.
- Sufficient strikes around target band/span.

## Fail-safe rule
If required columns or same-day bars are missing, run should fail fast instead of trading.

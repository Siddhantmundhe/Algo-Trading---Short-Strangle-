from __future__ import annotations

import argparse
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd
from dotenv import dotenv_values
from kiteconnect import KiteConnect


ROOT = Path(__file__).resolve().parent.parent


def _pick_existing(paths: Iterable[Path]) -> Optional[Path]:
    for p in paths:
        if p.exists():
            return p
    return None


def _load_kite(env_path: Path, token_path: Path) -> KiteConnect:
    vals = dotenv_values(env_path)
    api_key = (vals.get("KITE_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError(f"KITE_API_KEY missing in {env_path}")

    if not token_path.exists():
        raise RuntimeError(f"Token file not found: {token_path}")
    token = token_path.read_text(encoding="utf-8").strip()
    if not token:
        raise RuntimeError(f"Token empty: {token_path}")

    kite = KiteConnect(api_key=api_key)
    kite.set_access_token(token)
    profile = kite.profile()
    print(f"Auth OK | {profile.get('user_name') or profile.get('user_id')}")
    return kite


def _chunked_historical(
    kite: KiteConnect,
    instrument_token: int,
    from_dt: datetime,
    to_dt: datetime,
    interval: str = "5minute",
    chunk_days: int = 30,
) -> List[dict]:
    rows: List[dict] = []
    cur = from_dt
    while cur < to_dt:
        nxt = min(cur + timedelta(days=chunk_days), to_dt)
        candles = kite.historical_data(
            instrument_token=instrument_token,
            from_date=cur,
            to_date=nxt,
            interval=interval,
            continuous=False,
            oi=False,
        )
        rows.extend(candles or [])
        cur = nxt + timedelta(minutes=1)
    return rows


def _nearest_index_future(instruments: pd.DataFrame, index_name: str, ref_date: datetime) -> pd.Series:
    fut = instruments[
        (instruments["exchange"].astype(str).str.upper() == "NFO")
        & (instruments["segment"].astype(str).str.upper() == "NFO-FUT")
        & (instruments["name"].astype(str).str.upper() == str(index_name).upper())
    ].copy()
    fut["expiry"] = pd.to_datetime(fut["expiry"], errors="coerce")
    fut = fut.dropna(subset=["expiry"])
    fut = fut[fut["expiry"].dt.date >= ref_date.date()].sort_values("expiry")
    if fut.empty:
        raise RuntimeError(f"No active {index_name} futures contract found in instruments.")
    return fut.iloc[0]


def _round_to_step(x: float, step: int) -> int:
    return int(round(float(x) / step) * step)


def _build_index_option_contracts(
    instruments: pd.DataFrame,
    index_name: str,
    min_strike: int,
    max_strike: int,
    active_expiry_count: int,
) -> pd.DataFrame:
    opt = instruments[
        (instruments["exchange"].astype(str).str.upper() == "NFO")
        & (instruments["segment"].astype(str).str.upper() == "NFO-OPT")
        & (instruments["name"].astype(str).str.upper() == str(index_name).upper())
    ].copy()

    opt["expiry"] = pd.to_datetime(opt["expiry"], errors="coerce")
    opt["strike"] = pd.to_numeric(opt["strike"], errors="coerce")
    opt = opt.dropna(subset=["expiry", "strike"])

    today = datetime.now().date()
    opt = opt[opt["expiry"].dt.date >= today]
    opt = opt[(opt["strike"] >= min_strike) & (opt["strike"] <= max_strike)]
    opt = opt[opt["instrument_type"].astype(str).str.upper().isin(["CE", "PE"])]

    if opt.empty:
        raise RuntimeError("No option contracts matched selected range.")

    expiries = sorted(opt["expiry"].dropna().dt.date.unique().tolist())
    keep_exp = set(expiries[: max(1, int(active_expiry_count))])
    opt = opt[opt["expiry"].dt.date.isin(keep_exp)].copy()
    if opt.empty:
        raise RuntimeError("No option contracts after applying active expiry filter.")

    return opt.sort_values(["expiry", "strike", "instrument_type"]).reset_index(drop=True)


def fetch_underlying_5m(
    kite: KiteConnect,
    instruments: pd.DataFrame,
    index_name: str,
    from_dt: datetime,
    to_dt: datetime,
    out_csv: Path,
) -> pd.DataFrame:
    fut = _nearest_index_future(instruments, index_name=index_name, ref_date=to_dt)
    token = int(fut["instrument_token"])
    symbol = str(fut["tradingsymbol"])
    print(f"Fetching underlying FUT: {symbol} | token={token}")

    rows = _chunked_historical(kite, token, from_dt, to_dt, interval="5minute", chunk_days=60)
    if not rows:
        raise RuntimeError("No underlying candles fetched.")

    df = pd.DataFrame(rows)
    df["datetime"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["datetime"]).copy()
    df = df.rename(columns={"open": "open", "high": "high", "low": "low", "close": "close"})
    df = df[["datetime", "open", "high", "low", "close", "volume"]].sort_values("datetime").drop_duplicates(
        subset=["datetime"]
    )
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv, index=False)
    print(f"Saved underlying candles: {len(df)} rows -> {out_csv}")
    return df


def fetch_options_5m(
    kite: KiteConnect,
    contracts: pd.DataFrame,
    from_dt: datetime,
    to_dt: datetime,
    out_csv: Path,
    max_contracts: int = 0,
) -> pd.DataFrame:
    rows_out: List[pd.DataFrame] = []
    total = len(contracts) if max_contracts <= 0 else min(len(contracts), max_contracts)
    print(f"Fetching options candles for {total} contracts...")

    for i, (_, row) in enumerate(contracts.head(total).iterrows(), start=1):
        token = int(row["instrument_token"])
        symbol = str(row["tradingsymbol"])
        expiry = pd.to_datetime(row["expiry"]).date()
        strike = float(row["strike"])
        otype = str(row["instrument_type"]).upper()

        try:
            raw = _chunked_historical(kite, token, from_dt, to_dt, interval="5minute", chunk_days=20)
        except Exception as e:
            print(f"[WARN] {i}/{total} failed {symbol}: {e}")
            continue

        if not raw:
            continue
        d = pd.DataFrame(raw)
        d["datetime"] = pd.to_datetime(d["date"], errors="coerce")
        d = d.dropna(subset=["datetime"]).copy()
        d["expiry"] = expiry
        d["strike"] = strike
        d["option_type"] = otype
        d["symbol"] = symbol
        d = d[["datetime", "expiry", "strike", "option_type", "symbol", "open", "high", "low", "close", "volume"]]
        rows_out.append(d)

        if i % 25 == 0:
            print(f"  progress {i}/{total}")

    if not rows_out:
        raise RuntimeError("No option candles fetched.")

    out = pd.concat(rows_out, ignore_index=True)
    out = out.sort_values(["datetime", "expiry", "option_type", "strike"]).drop_duplicates(
        subset=["datetime", "expiry", "option_type", "strike", "symbol"]
    )
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_csv, index=False)
    print(f"Saved options candles: {len(out)} rows -> {out_csv}")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch index underlying/options candles for strangle backtests")
    parser.add_argument("--index", choices=["NIFTY", "BANKNIFTY"], default="NIFTY")
    parser.add_argument("--lookback-days", type=int, default=45)
    parser.add_argument("--strike-buffer-points", type=int, default=1000)
    parser.add_argument("--max-contracts", type=int, default=0, help="0 => all matched contracts")
    parser.add_argument("--active-expiry-count", type=int, default=3, help="Nearest active expiries to include")
    parser.add_argument("--env-path", default=None, help="Path to .env (optional)")
    parser.add_argument("--token-path", default=None, help="Path to access_token.txt (optional)")
    parser.add_argument("--instruments-path", default=None, help="Path to instruments.csv (optional)")
    args = parser.parse_args()

    default_env = _pick_existing([ROOT / ".env", ROOT.parent / "kite-login" / ".env"])
    default_token = _pick_existing(
        [ROOT / "broker" / "access_token.txt", ROOT.parent / "kite-login" / "broker" / "access_token.txt"]
    )
    default_instruments = _pick_existing([ROOT / "data" / "instruments.csv", ROOT.parent / "kite-login" / "instruments.csv"])

    env_path = Path(args.env_path) if args.env_path else default_env
    token_path = Path(args.token_path) if args.token_path else default_token
    instruments_path = Path(args.instruments_path) if args.instruments_path else default_instruments

    if env_path is None or token_path is None or instruments_path is None:
        raise RuntimeError("Could not resolve env/token/instruments paths. Pass them explicitly.")

    print(f"Using env: {env_path}")
    print(f"Using token: {token_path}")
    print(f"Using instruments: {instruments_path}")

    kite = _load_kite(env_path=env_path, token_path=token_path)
    instruments = pd.read_csv(instruments_path)

    index_name = str(args.index).upper()
    to_dt = datetime.now()
    from_dt = to_dt - timedelta(days=int(args.lookback_days))

    suffix = "" if index_name == "NIFTY" else "_banknifty"
    underlying_csv = ROOT / "data" / f"underlying_5m{suffix}.csv"
    options_csv = ROOT / "data" / f"options_5m{suffix}.csv"

    under = fetch_underlying_5m(kite, instruments, index_name, from_dt, to_dt, underlying_csv)
    min_under = float(under["close"].min())
    max_under = float(under["close"].max())

    step = 100 if index_name == "BANKNIFTY" else 50
    min_strike = _round_to_step(min_under - int(args.strike_buffer_points), step)
    max_strike = _round_to_step(max_under + int(args.strike_buffer_points), step)
    print(f"Strike window: {min_strike} .. {max_strike}")

    contracts = _build_index_option_contracts(
        instruments=instruments,
        index_name=index_name,
        min_strike=min_strike,
        max_strike=max_strike,
        active_expiry_count=int(args.active_expiry_count),
    )
    print(f"Contracts selected: {len(contracts)}")

    fetch_options_5m(
        kite=kite,
        contracts=contracts,
        from_dt=from_dt,
        to_dt=to_dt,
        out_csv=options_csv,
        max_contracts=int(args.max_contracts),
    )

    print("Done.")


if __name__ == "__main__":
    main()

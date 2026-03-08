from __future__ import annotations

import argparse
import json
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Dict

import pandas as pd

from scripts.fetch_data import (
    ROOT,
    _build_index_option_contracts,
    _load_kite,
    _pick_existing,
    _round_to_step,
    fetch_options_5m,
    fetch_underlying_5m,
)
from scripts.session_replay import build_backtest_config, load_json, resolve_available_date
from src.engine.backtest_engine import load_market_data, run_backtest_preloaded


def _suffix_from_index(index_name: str) -> str:
    return "_banknifty" if str(index_name).upper() == "BANKNIFTY" else ""


def _resolve_paths() -> tuple[Path, Path, Path]:
    env_path = _pick_existing([ROOT / ".env", ROOT.parent / "kite-login" / ".env"])
    token_path = _pick_existing(
        [ROOT / "broker" / "access_token.txt", ROOT.parent / "kite-login" / "broker" / "access_token.txt"]
    )
    instruments_path = _pick_existing([ROOT / "data" / "instruments.csv", ROOT.parent / "kite-login" / "instruments.csv"])

    if env_path is None or token_path is None or instruments_path is None:
        raise RuntimeError("Could not resolve env/token/instruments paths.")
    return env_path, token_path, instruments_path


def _parse_date(value: str | None) -> date:
    if not value:
        return datetime.now().date()
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        raise RuntimeError(f"Invalid --date: {value}. Use YYYY-MM-DD.")
    return parsed.date()


def _merge_into_csv(existing_path: Path, fetched: pd.DataFrame, subset: list[str]) -> None:
    if existing_path.exists():
        existing = pd.read_csv(existing_path)
        merged = pd.concat([existing, fetched], ignore_index=True)
    else:
        merged = fetched.copy()
    merged = merged.drop_duplicates(subset=subset).sort_values(subset).reset_index(drop=True)
    existing_path.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(existing_path, index=False)


def _build_fetch_window(target_date: date, live_cfg: Dict[str, Any]) -> tuple[datetime, datetime]:
    market_start = str(live_cfg.get("market_start", "09:15"))
    market_end = str(live_cfg.get("market_end", "15:30"))
    start_h, start_m = [int(x) for x in market_start.split(":")]
    end_h, end_m = [int(x) for x in market_end.split(":")]

    start_dt = datetime.combine(target_date, time(start_h, start_m))
    end_dt = datetime.combine(target_date, time(end_h, end_m))
    now = datetime.now()

    if target_date == now.date():
        end_dt = min(end_dt, now)
    if end_dt <= start_dt:
        raise RuntimeError("Fetch window is empty. Run this after market data is available.")
    return start_dt, end_dt


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch one trading session and replay it from the live config.")
    parser.add_argument("--config", default="configs/live/strangle_live_top2.json", help="Live config JSON")
    parser.add_argument("--date", default=None, help="Trade date YYYY-MM-DD. Defaults to today.")
    parser.add_argument("--strike-buffer-points", type=int, default=1000)
    parser.add_argument("--active-expiry-count", type=int, default=3)
    parser.add_argument("--max-contracts", type=int, default=0, help="0 => all matched contracts")
    parser.add_argument("--output-name", default=None, help="Optional replay output path under reports/")
    args = parser.parse_args()

    live_cfg = load_json(args.config)
    index_name = str(live_cfg.get("index", "NIFTY")).upper()
    target_date = _parse_date(args.date)
    start_dt, end_dt = _build_fetch_window(target_date, live_cfg)

    env_path, token_path, instruments_path = _resolve_paths()
    kite = _load_kite(env_path=env_path, token_path=token_path)
    instruments = pd.read_csv(instruments_path)

    suffix = _suffix_from_index(index_name)
    underlying_csv = ROOT / "data" / f"underlying_5m{suffix}.csv"
    options_csv = ROOT / "data" / f"options_5m{suffix}.csv"
    temp_dir = ROOT / "reports" / "tmp"
    underlying_tmp = temp_dir / f"underlying_5m{suffix}_{target_date.isoformat()}.csv"
    options_tmp = temp_dir / f"options_5m{suffix}_{target_date.isoformat()}.csv"

    under = fetch_underlying_5m(kite, instruments, index_name, start_dt, end_dt, underlying_tmp)
    min_under = float(under["close"].min())
    max_under = float(under["close"].max())
    step = 100 if index_name == "BANKNIFTY" else 50
    min_strike = _round_to_step(min_under - int(args.strike_buffer_points), step)
    max_strike = _round_to_step(max_under + int(args.strike_buffer_points), step)

    contracts = _build_index_option_contracts(
        instruments=instruments,
        index_name=index_name,
        min_strike=min_strike,
        max_strike=max_strike,
        active_expiry_count=int(args.active_expiry_count),
    )
    opt = fetch_options_5m(
        kite=kite,
        contracts=contracts,
        from_dt=start_dt,
        to_dt=end_dt,
        out_csv=options_tmp,
        max_contracts=int(args.max_contracts),
    )

    _merge_into_csv(underlying_csv, under, subset=["datetime"])
    _merge_into_csv(options_csv, opt, subset=["datetime", "expiry", "option_type", "strike", "symbol"])

    out_name = args.output_name or f"replay/{index_name.lower()}/session_replay_{target_date.isoformat()}.csv"
    bt_cfg = build_backtest_config(live_cfg, out_name=out_name)
    under_all, opt_all, _ = load_market_data(bt_cfg)
    picked_date = resolve_available_date(under_all, target_date.isoformat(), nearest_previous=False)

    day_under = under_all[under_all["trade_date"] == picked_date].copy()
    day_opt = opt_all[opt_all["trade_date"] == picked_date].copy()
    bt_cfg["name"] = f"session_replay_{index_name.lower()}_{picked_date}"
    result = run_backtest_preloaded(bt_cfg, day_under, day_opt)

    print(
        json.dumps(
            {
                "index": index_name,
                "date": picked_date,
                "underlying_csv": str(underlying_csv),
                "options_csv": str(options_csv),
                **result,
            },
            indent=2,
            default=str,
        )
    )


if __name__ == "__main__":
    main()

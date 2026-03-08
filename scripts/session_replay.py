from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd

import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.engine.backtest_engine import load_market_data, run_backtest_preloaded


def load_json(path: str | Path) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _suffix_from_index(index_name: str) -> str:
    return "_banknifty" if str(index_name).upper() == "BANKNIFTY" else ""


def build_backtest_config(live_cfg: Dict[str, Any], out_name: str) -> Dict[str, Any]:
    index_name = str(live_cfg.get("index", "NIFTY")).upper()
    suffix = _suffix_from_index(index_name)

    cfg: Dict[str, Any] = {
        "name": f"session_replay_{index_name.lower()}",
        "underlying_data": f"data/underlying_5m{suffix}.csv",
        "options_data": f"data/options_5m{suffix}.csv",
        "output_name": out_name,
        "save_trades": True,
        "lot_size": int(live_cfg.get("lot_size", 50)),
        "lots": int(live_cfg.get("lots", 1)),
        "strike_step": int(live_cfg.get("strike_step", 50)),
        "strike_method": str(live_cfg.get("strike_method", "delta_target")),
        "entry_time": str(live_cfg.get("entry_time", "09:20")),
        "exit_time": str(live_cfg.get("exit_time", "15:20")),
        "premium_target_per_leg": float(live_cfg.get("premium_target_per_leg", 60)),
        "premium_band": float(live_cfg.get("premium_band", 20)),
        "fixed_distance_points": int(live_cfg.get("fixed_distance_points", 300)),
        "target_delta_ce": float(live_cfg.get("target_delta_ce", 0.15)),
        "target_delta_pe": float(live_cfg.get("target_delta_pe", -0.15)),
        "per_leg_sl_pct": float(live_cfg.get("per_leg_sl_pct", 30)),
        "combined_mtm_sl_rupees": float(live_cfg.get("combined_mtm_sl_rupees", 2000)),
        "combined_mtm_target_rupees": float(live_cfg.get("combined_mtm_target_rupees", 1500)),
        "slippage_per_order_rupees": float(live_cfg.get("slippage_per_order_rupees", 5)),
        "charges_per_lot_roundtrip_rupees": float(live_cfg.get("charges_per_lot_roundtrip_rupees", 40)),
    }

    # Allow explicit data path override from live config if present.
    if "underlying_data" in live_cfg:
        cfg["underlying_data"] = str(live_cfg["underlying_data"])
    if "options_data" in live_cfg:
        cfg["options_data"] = str(live_cfg["options_data"])

    return cfg


def pick_target_date(under: pd.DataFrame, date_arg: Optional[str]) -> str:
    if date_arg:
        d = pd.to_datetime(date_arg, errors="coerce")
        if pd.isna(d):
            raise RuntimeError(f"Invalid --date: {date_arg}. Use YYYY-MM-DD.")
        return str(d.date())
    return str(sorted(under["trade_date"].unique().tolist())[-1])


def resolve_available_date(
    under: pd.DataFrame,
    target_date: str,
    nearest_previous: bool,
) -> str:
    available = sorted(under["trade_date"].unique().tolist())
    if target_date in set(available):
        return target_date

    if not nearest_previous:
        raise RuntimeError(
            f"No underlying candles found for {target_date}. "
            f"Available range: {available[0]} to {available[-1]}. "
            f"Use --nearest-previous or refresh data with scripts/fetch_data.py."
        )

    td = pd.to_datetime(target_date).date()
    prev = [d for d in available if pd.to_datetime(d).date() <= td]
    if not prev:
        raise RuntimeError(
            f"No data on/before {target_date}. Available range starts at {available[0]}."
        )
    picked = prev[-1]
    print(f"[info] Requested date {target_date} not in dataset. Using nearest previous: {picked}")
    return picked


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay one market session from saved data using live strategy config")
    parser.add_argument("--config", default="configs/live/strangle_live_top2.json", help="Live config JSON")
    parser.add_argument("--date", default=None, help="Trade date YYYY-MM-DD (default: latest available in data)")
    parser.add_argument(
        "--nearest-previous",
        action="store_true",
        help="If --date is missing in dataset, replay nearest previous available date.",
    )
    parser.add_argument("--output-name", default=None, help="Optional report output path under reports/")
    args = parser.parse_args()

    live_cfg = load_json(args.config)
    index_name = str(live_cfg.get("index", "NIFTY")).upper()

    date_hint = str(args.date) if args.date else "latest"
    out_name = args.output_name or f"replay/{index_name.lower()}/session_replay_{date_hint}.csv"
    bt_cfg = build_backtest_config(live_cfg, out_name=out_name)

    under, opt, _ = load_market_data(bt_cfg)
    requested_date = pick_target_date(under, args.date)
    target_date = resolve_available_date(under, requested_date, nearest_previous=bool(args.nearest_previous))

    day_under = under[under["trade_date"] == target_date].copy()
    day_opt = opt[opt["trade_date"] == target_date].copy()

    if day_under.empty:
        raise RuntimeError(
            f"No underlying candles found for {target_date} in {bt_cfg['underlying_data']}. "
            f"Refresh data with scripts/fetch_data.py."
        )
    if day_opt.empty:
        raise RuntimeError(f"No options candles found for {target_date} in {bt_cfg['options_data']}")

    bt_cfg["name"] = f"session_replay_{index_name.lower()}_{target_date}"
    result = run_backtest_preloaded(bt_cfg, day_under, day_opt)

    print("Session replay result:")
    print(f"index: {index_name}")
    print(f"date: {target_date}")
    for k, v in result.items():
        print(f"{k}: {v}")


if __name__ == "__main__":
    main()

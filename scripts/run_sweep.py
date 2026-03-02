from __future__ import annotations

import argparse
import itertools
from pathlib import Path
import sys
import json
import random

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.engine.backtest_engine import load_config, load_market_data, run_backtest_preloaded
from src.analytics.metrics import risk_adjusted_score


def _is_valid_combo(cfg: dict) -> bool:
    method = str(cfg.get("strike_method", "")).lower().strip()

    # Method-specific masks to avoid meaningless grid inflation.
    if method == "premium_target":
        # fixed distance and deltas are irrelevant
        if cfg.get("fixed_distance_points", None) not in (None, 200):
            return False
        if cfg.get("target_delta_ce", None) not in (None, 0.2):
            return False
        if cfg.get("target_delta_pe", None) not in (None, -0.2):
            return False

    elif method == "fixed_distance":
        # premium target band and deltas are irrelevant
        if cfg.get("premium_target_per_leg", None) not in (None, 60):
            return False
        if cfg.get("premium_band", None) not in (None, 20):
            return False
        if cfg.get("target_delta_ce", None) not in (None, 0.2):
            return False
        if cfg.get("target_delta_pe", None) not in (None, -0.2):
            return False

    elif method == "delta_target":
        # premium target and fixed distance are irrelevant
        if cfg.get("premium_target_per_leg", None) not in (None, 60):
            return False
        if cfg.get("premium_band", None) not in (None, 20):
            return False
        if cfg.get("fixed_distance_points", None) not in (None, 300):
            return False
    else:
        return False

    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--max-combos", type=int, default=0, help="0 means run all")
    parser.add_argument("--sample-random", type=int, default=0, help="Sample N random valid combos before execution")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    sweep = load_config(args.config)
    base = load_config(sweep["base_config"])
    grid = sweep["grid"]
    under, opt, _ = load_market_data(base)

    keys = list(grid.keys())
    raw_combos = list(itertools.product(*[grid[k] for k in keys]))

    # Build filtered config list first.
    cfgs = []
    for combo in raw_combos:
        cfg = dict(base)
        for k, v in zip(keys, combo):
            cfg[k] = v
        if _is_valid_combo(cfg):
            cfgs.append(cfg)

    if args.sample_random and args.sample_random > 0 and len(cfgs) > args.sample_random:
        rng = random.Random(args.seed)
        cfgs = rng.sample(cfgs, args.sample_random)

    if args.max_combos and args.max_combos > 0:
        cfgs = cfgs[: args.max_combos]

    print(f"Total grid combos: {len(raw_combos)}")
    print(f"Valid method-aware combos: {len(cfgs)}")

    rows = []
    for i, cfg in enumerate(cfgs, start=1):
        cfg["output_name"] = f"sweep_tradebook_{i:05d}.csv"
        cfg["save_trades"] = False

        res = run_backtest_preloaded(cfg, under, opt)
        row = {**cfg, **res}
        row["score"] = risk_adjusted_score(row)
        rows.append(row)

    if not rows:
        print("No combinations executed.")
        return

    out_df = pd.DataFrame(rows).sort_values(["score", "net_pnl"], ascending=[False, False]).reset_index(drop=True)

    top20_json = ROOT / "reports" / str(sweep.get("output_top20_json", "sweep_top20.json"))
    full_csv = ROOT / "reports" / str(sweep.get("output_full_csv", "sweep_results.csv"))
    top20_json.parent.mkdir(parents=True, exist_ok=True)
    full_csv.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(full_csv, index=False)
    top20_json.write_text(out_df.head(20).to_json(orient="records", indent=2), encoding="utf-8")

    print(f"Saved full sweep to {full_csv}")
    print(f"Saved top 20 to {top20_json}")


if __name__ == "__main__":
    main()

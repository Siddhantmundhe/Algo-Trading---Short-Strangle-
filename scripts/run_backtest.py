from __future__ import annotations

import argparse
from pathlib import Path
import sys
import json

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.engine.backtest_engine import load_config, run_backtest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--override", default=None, help="Optional JSON string of config overrides")
    args = parser.parse_args()

    config = load_config(args.config)
    if args.override:
        config.update(json.loads(args.override))

    result = run_backtest(config)
    print("Backtest result:")
    for k, v in result.items():
        print(f"{k}: {v}")


if __name__ == "__main__":
    main()

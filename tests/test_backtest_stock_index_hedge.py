from __future__ import annotations

import unittest
from datetime import datetime

import pandas as pd

from scripts.backtest_stock_index_hedge import (
    _continuous_anchor_future,
    _normalize_history,
)


class BacktestStockIndexHedgeTests(unittest.TestCase):
    def test_continuous_anchor_future_picks_nearest_active_contract(self) -> None:
        futures = pd.DataFrame(
            [
                {"tradingsymbol": "NIFTY26FEBFUT", "expiry": "2026-02-24", "instrument_token": 1, "lot_size": 65},
                {"tradingsymbol": "NIFTY26MARFUT", "expiry": "2026-03-30", "instrument_token": 2, "lot_size": 65},
                {"tradingsymbol": "NIFTY26APRFUT", "expiry": "2026-04-28", "instrument_token": 3, "lot_size": 65},
            ]
        )
        futures["expiry"] = pd.to_datetime(futures["expiry"])

        picked = _continuous_anchor_future(futures, datetime(2026, 3, 8))

        self.assertEqual(str(picked["tradingsymbol"]), "NIFTY26MARFUT")

    def test_normalize_history_deduplicates_and_renames_columns(self) -> None:
        rows = [
            {"date": "2026-02-06T00:00:00+05:30", "open": 100.0, "high": 105.0, "low": 99.0, "close": 102.0},
            {"date": "2026-02-06T00:00:00+05:30", "open": 101.0, "high": 106.0, "low": 100.0, "close": 103.0},
            {"date": "2026-02-07T00:00:00+05:30", "open": 104.0, "high": 107.0, "low": 103.0, "close": 106.0},
        ]

        out = _normalize_history(rows, "stock")

        self.assertEqual(list(out.columns), ["date", "stock_open", "stock_high", "stock_low", "stock_close"])
        self.assertEqual(len(out), 2)
        self.assertEqual(out.iloc[0]["stock_close"], 102.0)


if __name__ == "__main__":
    unittest.main()

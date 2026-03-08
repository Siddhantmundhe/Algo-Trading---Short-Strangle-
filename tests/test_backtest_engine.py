from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.engine.backtest_engine import _compute_summary, run_backtest


class BacktestEngineTests(unittest.TestCase):
    def test_compute_summary_handles_empty_trades(self) -> None:
        summary = _compute_summary(pd.DataFrame())

        self.assertEqual(summary["trades"], 0)
        self.assertEqual(summary["net_pnl"], 0.0)
        self.assertEqual(summary["profit_factor"], 0.0)

    def test_compute_summary_calculates_drawdown_and_profit_factor(self) -> None:
        trades = pd.DataFrame(
            {
                "net_pnl_rupees": [100.0, -50.0, 25.0],
                "gross_pnl_rupees": [120.0, -30.0, 40.0],
            }
        )

        summary = _compute_summary(trades)

        self.assertEqual(summary["trades"], 3)
        self.assertEqual(summary["net_pnl"], 75.0)
        self.assertEqual(summary["max_drawdown"], -50.0)
        self.assertAlmostEqual(summary["profit_factor"], 2.5)

    def test_run_backtest_returns_missing_data_status_when_csvs_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = {
                "name": "missing_data_case",
                "underlying_data": str(Path(tmp) / "missing_under.csv"),
                "options_data": str(Path(tmp) / "missing_opt.csv"),
            }

            result = run_backtest(config)

            self.assertEqual(result["status"], "missing_data")
            self.assertEqual(result["trades"], 0)


if __name__ == "__main__":
    unittest.main()

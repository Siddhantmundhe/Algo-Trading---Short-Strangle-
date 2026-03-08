from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

import pandas as pd

from scripts.replay_from_fetched_data import _build_fetch_window, _merge_into_csv


class ReplayFromFetchedDataTests(unittest.TestCase):
    def test_build_fetch_window_for_past_date_uses_market_hours(self) -> None:
        live_cfg = {"market_start": "09:15", "market_end": "15:30"}

        start_dt, end_dt = _build_fetch_window(date(2026, 3, 6), live_cfg)

        self.assertEqual(start_dt.hour, 9)
        self.assertEqual(start_dt.minute, 15)
        self.assertEqual(end_dt.hour, 15)
        self.assertEqual(end_dt.minute, 30)

    def test_merge_into_csv_deduplicates_on_subset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.csv"
            pd.DataFrame(
                [{"datetime": "2026-03-06 09:15:00", "close": 100}, {"datetime": "2026-03-06 09:20:00", "close": 101}]
            ).to_csv(path, index=False)

            fetched = pd.DataFrame(
                [{"datetime": "2026-03-06 09:20:00", "close": 101}, {"datetime": "2026-03-06 09:25:00", "close": 102}]
            )
            _merge_into_csv(path, fetched, subset=["datetime"])

            out = pd.read_csv(path)
            self.assertEqual(len(out), 3)
            self.assertEqual(out.iloc[-1]["close"], 102)


if __name__ == "__main__":
    unittest.main()

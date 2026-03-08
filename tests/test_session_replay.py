from __future__ import annotations

import unittest

import pandas as pd

from scripts.session_replay import build_backtest_config, resolve_available_date


class SessionReplayTests(unittest.TestCase):
    def test_build_backtest_config_uses_banknifty_suffix_and_live_overrides(self) -> None:
        live_cfg = {
            "index": "BANKNIFTY",
            "entry_time": "09:25",
            "lots": 2,
            "strike_method": "delta_target",
            "underlying_data": "custom/under.csv",
            "options_data": "custom/options.csv",
        }

        cfg = build_backtest_config(live_cfg, out_name="replay/out.csv")

        self.assertEqual(cfg["underlying_data"], "custom/under.csv")
        self.assertEqual(cfg["options_data"], "custom/options.csv")
        self.assertEqual(cfg["entry_time"], "09:25")
        self.assertEqual(cfg["lots"], 2)
        self.assertEqual(cfg["name"], "session_replay_banknifty")

    def test_resolve_available_date_picks_nearest_previous_when_enabled(self) -> None:
        under = pd.DataFrame({"trade_date": ["2026-03-03", "2026-03-04", "2026-03-06"]})

        picked = resolve_available_date(under, "2026-03-05", nearest_previous=True)

        self.assertEqual(picked, "2026-03-04")


if __name__ == "__main__":
    unittest.main()

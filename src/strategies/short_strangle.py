from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class LegSelection:
    option_type: str
    strike: float
    entry_price: float
    symbol: Optional[str] = None


def _atm_strike(underlying: float, step: int) -> float:
    return float(int(round(float(underlying) / float(step)) * step))


def _delta_proxy(option_type: str, strike: float, underlying: float, step: int) -> float:
    # Simple monotonic proxy when true greeks are unavailable.
    # ATM magnitude ~0.50; farther OTM decays exponentially.
    distance_steps = abs(float(strike) - float(underlying)) / max(float(step), 1.0)
    mag = 0.5 * float(np.exp(-0.35 * distance_steps))
    if option_type.upper() == "CE":
        return mag
    return -mag


def select_leg(
    options_snapshot: pd.DataFrame,
    option_type: str,
    strike_method: str,
    underlying_price: float,
    step: int,
    premium_target: float,
    premium_band: float,
    fixed_distance_points: int,
    target_delta: float,
) -> Optional[LegSelection]:
    df = options_snapshot.copy()
    df = df[df["option_type"].astype(str).str.upper() == option_type.upper()].copy()
    if df.empty:
        return None

    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df["strike"] = pd.to_numeric(df["strike"], errors="coerce")
    df = df.dropna(subset=["close", "strike"])
    if df.empty:
        return None

    method = str(strike_method).lower().strip()

    if method == "premium_target":
        target = float(premium_target)
        band = float(max(premium_band, 0))
        cand = df[(df["close"] >= (target - band)) & (df["close"] <= (target + band))].copy()
        if cand.empty:
            cand = df.copy()
        cand["score"] = (cand["close"] - target).abs()
        pick = cand.sort_values(["score", "strike"]).iloc[0]

    elif method == "fixed_distance":
        atm = _atm_strike(underlying_price, step)
        if option_type.upper() == "CE":
            wanted = atm + float(fixed_distance_points)
        else:
            wanted = atm - float(fixed_distance_points)
        cand = df.copy()
        cand["score"] = (cand["strike"] - wanted).abs()
        pick = cand.sort_values(["score", "strike"]).iloc[0]

    elif method == "delta_target":
        wanted = float(target_delta)
        if option_type.upper() == "PE" and wanted > 0:
            wanted = -wanted
        if option_type.upper() == "CE" and wanted < 0:
            wanted = abs(wanted)

        if "delta" in df.columns:
            d = pd.to_numeric(df["delta"], errors="coerce")
            cand = df[d.notna()].copy()
            cand["delta_used"] = d[d.notna()]
        else:
            cand = df.copy()
            cand["delta_used"] = cand["strike"].apply(lambda x: _delta_proxy(option_type, x, underlying_price, step))

        if cand.empty:
            return None
        cand["score"] = (cand["delta_used"] - wanted).abs()
        pick = cand.sort_values(["score", "strike"]).iloc[0]

    else:
        raise ValueError(f"Unknown strike_method: {strike_method}")

    return LegSelection(
        option_type=option_type.upper(),
        strike=float(pick["strike"]),
        entry_price=float(pick["close"]),
        symbol=str(pick["symbol"]) if "symbol" in pick.index else None,
    )

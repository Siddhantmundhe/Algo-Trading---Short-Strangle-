from __future__ import annotations

from typing import Dict, Any


def risk_adjusted_score(row: Dict[str, Any]) -> float:
    net = float(row.get("net_pnl", 0.0))
    dd = abs(float(row.get("max_drawdown", 1.0)))
    win = float(row.get("win_rate", 0.0))
    return (net / max(dd, 1.0)) + (0.01 * win)

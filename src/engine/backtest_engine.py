from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from src.strategies.short_strangle import LegSelection, select_leg


ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass
class LegState:
    option_type: str
    strike: float
    entry_price: float
    qty: int
    is_open: bool = True
    exit_price: Optional[float] = None
    exit_time: Optional[pd.Timestamp] = None
    exit_reason: Optional[str] = None

    def realized_points(self) -> float:
        if self.exit_price is None:
            return 0.0
        # short option: pnl points = entry - exit
        return float(self.entry_price) - float(self.exit_price)


@dataclass
class TradeResult:
    trade_date: str
    entry_time: pd.Timestamp
    expiry: str
    method: str
    ce_strike: float
    pe_strike: float
    ce_entry: float
    pe_entry: float
    ce_exit: float
    pe_exit: float
    ce_exit_reason: str
    pe_exit_reason: str
    gross_pnl_rupees: float
    costs_rupees: float
    net_pnl_rupees: float
    max_intraday_drawdown_rupees: float
    combined_exit_reason: str


def load_config(path: str | Path) -> Dict[str, Any]:
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8-sig"))


def _parse_hhmm(hhmm: str) -> Tuple[int, int]:
    h, m = hhmm.split(":")
    return int(h), int(m)


def _ensure_dt_col(df: pd.DataFrame, candidates: List[str]) -> str:
    for c in candidates:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors="coerce")
            return c
    raise ValueError(f"Missing datetime column. Tried: {candidates}")


def _load_underlying(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    dt_col = _ensure_dt_col(df, ["datetime", "date", "timestamp", "time"])
    df = df.dropna(subset=[dt_col]).copy()
    df = df.rename(columns={dt_col: "datetime"})

    for c in ["open", "high", "low", "close"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"]).copy()

    df = df.sort_values("datetime").reset_index(drop=True)
    df["trade_date"] = df["datetime"].dt.date.astype(str)
    return df


def _load_options(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)

    dt_col = _ensure_dt_col(df, ["datetime", "date", "timestamp", "time"])
    df = df.rename(columns={dt_col: "datetime"})

    if "option_type" not in df.columns and "instrument_type" in df.columns:
        df = df.rename(columns={"instrument_type": "option_type"})

    if "symbol" not in df.columns and "tradingsymbol" in df.columns:
        df = df.rename(columns={"tradingsymbol": "symbol"})

    required = ["datetime", "expiry", "strike", "option_type", "open", "high", "low", "close"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Options data missing required columns: {missing}")

    df["expiry"] = pd.to_datetime(df["expiry"], errors="coerce").dt.date
    for c in ["strike", "open", "high", "low", "close"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["option_type"] = df["option_type"].astype(str).str.upper()

    df = df.dropna(subset=["datetime", "expiry", "strike", "open", "high", "low", "close"]).copy()
    df = df.sort_values(["datetime", "expiry", "option_type", "strike"]).reset_index(drop=True)
    df["trade_date"] = df["datetime"].dt.date.astype(str)
    return df


def _pick_expiry(options_at_entry: pd.DataFrame, trade_day: str) -> Optional[Any]:
    if options_at_entry.empty:
        return None
    d = pd.to_datetime(trade_day).date()
    exp = options_at_entry[options_at_entry["expiry"] >= d]["expiry"].dropna().sort_values().unique()
    if len(exp) == 0:
        return None
    return exp[0]


def _mark_leg_close(ts_df: pd.DataFrame, leg: LegState, col: str) -> Optional[float]:
    row = ts_df[(ts_df["option_type"] == leg.option_type) & (ts_df["strike"] == leg.strike)]
    if row.empty:
        return None
    return float(row.iloc[0][col])


def _intraday_pnl_rupees(legs: List[LegState], ts_df: pd.DataFrame, lot_size: int) -> Optional[float]:
    mark = 0.0
    for leg in legs:
        if leg.is_open:
            px = _mark_leg_close(ts_df, leg, "close")
            if px is None:
                return None
            mark += (leg.entry_price - px) * leg.qty
        else:
            mark += leg.realized_points() * leg.qty
    return mark


def _simulate_day(
    day_under: pd.DataFrame,
    day_opt: pd.DataFrame,
    config: Dict[str, Any],
    lot_size: int,
) -> Optional[TradeResult]:
    h, m = _parse_hhmm(config["entry_time"])
    entry_rows = day_under[(day_under["datetime"].dt.hour == h) & (day_under["datetime"].dt.minute == m)]
    if entry_rows.empty:
        return None

    entry_ts = pd.to_datetime(entry_rows.iloc[0]["datetime"])
    trade_day = str(entry_ts.date())

    opt_entry_ts = day_opt[day_opt["datetime"] == entry_ts].copy()
    if opt_entry_ts.empty:
        return None

    expiry = _pick_expiry(opt_entry_ts, trade_day)
    if expiry is None:
        return None

    entry_snap = opt_entry_ts[opt_entry_ts["expiry"] == expiry].copy()
    if entry_snap.empty:
        return None

    underlying_px = float(entry_rows.iloc[0]["close"])

    strike_step = int(config.get("strike_step", 50))
    method = str(config.get("strike_method", "premium_target")).lower()

    ce_sel = select_leg(
        options_snapshot=entry_snap,
        option_type="CE",
        strike_method=method,
        underlying_price=underlying_px,
        step=strike_step,
        premium_target=float(config.get("premium_target_per_leg", 60)),
        premium_band=float(config.get("premium_band", 20)),
        fixed_distance_points=int(config.get("fixed_distance_points", 300)),
        target_delta=float(config.get("target_delta_ce", 0.2)),
    )
    pe_sel = select_leg(
        options_snapshot=entry_snap,
        option_type="PE",
        strike_method=method,
        underlying_price=underlying_px,
        step=strike_step,
        premium_target=float(config.get("premium_target_per_leg", 60)),
        premium_band=float(config.get("premium_band", 20)),
        fixed_distance_points=int(config.get("fixed_distance_points", 300)),
        target_delta=float(config.get("target_delta_pe", -0.2)),
    )

    if ce_sel is None or pe_sel is None:
        return None

    lots = int(config.get("lots", 1))
    qty = int(max(1, lots) * lot_size)

    ce = LegState("CE", ce_sel.strike, ce_sel.entry_price, qty)
    pe = LegState("PE", pe_sel.strike, pe_sel.entry_price, qty)
    legs: List[LegState] = [ce, pe]

    per_leg_sl_pct = float(config.get("per_leg_sl_pct", 40))
    ce_sl = ce.entry_price * (1.0 + per_leg_sl_pct / 100.0)
    pe_sl = pe.entry_price * (1.0 + per_leg_sl_pct / 100.0)

    combined_sl = float(config.get("combined_mtm_sl_rupees", 3000))
    combined_tgt = float(config.get("combined_mtm_target_rupees", 2500))

    eh, em = _parse_hhmm(config.get("exit_time", "15:20"))

    walk = day_opt[(day_opt["expiry"] == expiry) & (day_opt["datetime"] >= entry_ts)].copy()
    if walk.empty:
        return None

    times = sorted(walk["datetime"].dropna().unique())

    max_dd = 0.0
    combined_exit_reason = "EOD"

    for ts in times:
        ts = pd.to_datetime(ts)
        if ts.hour > eh or (ts.hour == eh and ts.minute > em):
            break

        ts_df = walk[walk["datetime"] == ts]

        # Per-leg stops on candle high for short options
        if ce.is_open:
            ce_h = _mark_leg_close(ts_df, ce, "high")
            if ce_h is not None and ce_h >= ce_sl:
                ce.is_open = False
                ce.exit_price = ce_sl
                ce.exit_time = ts
                ce.exit_reason = "LEG_SL"

        if pe.is_open:
            pe_h = _mark_leg_close(ts_df, pe, "high")
            if pe_h is not None and pe_h >= pe_sl:
                pe.is_open = False
                pe.exit_price = pe_sl
                pe.exit_time = ts
                pe.exit_reason = "LEG_SL"

        mtm = _intraday_pnl_rupees(legs, ts_df, lot_size)
        if mtm is None:
            continue
        max_dd = min(max_dd, mtm)

        if mtm <= -abs(combined_sl):
            for leg in legs:
                if leg.is_open:
                    px = _mark_leg_close(ts_df, leg, "close")
                    if px is not None:
                        leg.is_open = False
                        leg.exit_price = px
                        leg.exit_time = ts
                        leg.exit_reason = "COMBINED_SL"
            combined_exit_reason = "COMBINED_SL"
            break

        if mtm >= abs(combined_tgt):
            for leg in legs:
                if leg.is_open:
                    px = _mark_leg_close(ts_df, leg, "close")
                    if px is not None:
                        leg.is_open = False
                        leg.exit_price = px
                        leg.exit_time = ts
                        leg.exit_reason = "COMBINED_TGT"
            combined_exit_reason = "COMBINED_TGT"
            break

        if all(not leg.is_open for leg in legs):
            combined_exit_reason = "BOTH_LEGS_SL_OR_EXITED"
            break

    # EOD exit remaining legs at last available close <= exit_time
    eod_walk = walk[(walk["datetime"].dt.hour < eh) | ((walk["datetime"].dt.hour == eh) & (walk["datetime"].dt.minute <= em))]
    if not eod_walk.empty:
        last_ts = pd.to_datetime(eod_walk["datetime"].max())
        last_df = eod_walk[eod_walk["datetime"] == last_ts]
    else:
        last_ts = pd.to_datetime(walk["datetime"].max())
        last_df = walk[walk["datetime"] == last_ts]

    for leg in legs:
        if leg.is_open:
            px = _mark_leg_close(last_df, leg, "close")
            if px is not None:
                leg.is_open = False
                leg.exit_price = px
                leg.exit_time = last_ts
                leg.exit_reason = "EOD"

    if ce.exit_price is None or pe.exit_price is None:
        return None

    gross = (ce.realized_points() + pe.realized_points()) * qty

    slippage_per_order = float(config.get("slippage_per_order_rupees", 5.0))
    charges_per_lot_roundtrip = float(config.get("charges_per_lot_roundtrip_rupees", 40.0))
    # Two legs, each roundtrip once => 4 orders total.
    total_orders = 4
    slippage_cost = slippage_per_order * total_orders * max(1, lots)
    charge_cost = charges_per_lot_roundtrip * 2 * max(1, lots)
    costs = slippage_cost + charge_cost
    net = gross - costs

    return TradeResult(
        trade_date=trade_day,
        entry_time=entry_ts,
        expiry=str(expiry),
        method=method,
        ce_strike=ce.strike,
        pe_strike=pe.strike,
        ce_entry=ce.entry_price,
        pe_entry=pe.entry_price,
        ce_exit=ce.exit_price,
        pe_exit=pe.exit_price,
        ce_exit_reason=str(ce.exit_reason or ""),
        pe_exit_reason=str(pe.exit_reason or ""),
        gross_pnl_rupees=float(gross),
        costs_rupees=float(costs),
        net_pnl_rupees=float(net),
        max_intraday_drawdown_rupees=float(max_dd),
        combined_exit_reason=combined_exit_reason,
    )


def _compute_summary(trades_df: pd.DataFrame) -> Dict[str, Any]:
    if trades_df.empty:
        return {
            "trades": 0,
            "net_pnl": 0.0,
            "gross_pnl": 0.0,
            "max_drawdown": 0.0,
            "win_rate": 0.0,
            "avg_pnl": 0.0,
            "profit_factor": 0.0,
        }

    pnl = pd.to_numeric(trades_df["net_pnl_rupees"], errors="coerce").fillna(0.0)
    equity = pnl.cumsum()
    dd = equity - equity.cummax()

    wins = pnl[pnl > 0].sum()
    losses = pnl[pnl < 0].sum()
    pf = float(abs(wins / losses)) if float(losses) < 0 else 0.0

    return {
        "trades": int(len(trades_df)),
        "net_pnl": float(pnl.sum()),
        "gross_pnl": float(pd.to_numeric(trades_df["gross_pnl_rupees"], errors="coerce").fillna(0).sum()),
        "max_drawdown": float(dd.min()),
        "win_rate": float((pnl > 0).mean() * 100.0),
        "avg_pnl": float(pnl.mean()),
        "profit_factor": pf,
    }


def load_market_data(config: Dict[str, Any]) -> Tuple[pd.DataFrame, pd.DataFrame, Path]:
    underlying_path = ROOT / config.get("underlying_data", "data/underlying_5m.csv")
    options_path = ROOT / config.get("options_data", "data/options_5m.csv")

    if not underlying_path.exists() or not options_path.exists():
        raise FileNotFoundError(
            f"Missing data files: underlying={underlying_path.exists()} options={options_path.exists()} "
            f"| {underlying_path} | {options_path}"
        )

    under = _load_underlying(underlying_path)
    opt = _load_options(options_path)
    return under, opt, ROOT


def run_backtest_preloaded(config: Dict[str, Any], under: pd.DataFrame, opt: pd.DataFrame) -> Dict[str, Any]:
    lot_size = int(config.get("lot_size", 50))

    # Restrict options universe by index day overlap for faster per-combo loops.
    trade_days = set(under["trade_date"].unique().tolist())
    opt_use = opt[opt["trade_date"].isin(trade_days)].copy()

    day_rows = []
    for d in sorted(under["trade_date"].unique()):
        day_under = under[under["trade_date"] == d].copy()
        day_opt = opt_use[opt_use["trade_date"] == d].copy()
        if day_under.empty or day_opt.empty:
            continue

        tr = _simulate_day(day_under=day_under, day_opt=day_opt, config=config, lot_size=lot_size)
        if tr is not None:
            day_rows.append(asdict(tr))

    trades_df = pd.DataFrame(day_rows)
    summary = _compute_summary(trades_df)

    save_trades = bool(config.get("save_trades", True))
    out_name = config.get("output_name", f"{config.get('name', 'strangle')}_trades.csv")
    out_path = ROOT / "reports" / out_name
    if save_trades:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if not trades_df.empty:
            trades_df.to_csv(out_path, index=False)

    return {
        "strategy": config.get("name", "unknown"),
        "status": "ok",
        **summary,
        "report_path": str(out_path) if save_trades else "",
    }


def run_backtest(config: Dict[str, Any]) -> Dict[str, Any]:
    underlying_path = ROOT / config.get("underlying_data", "data/underlying_5m.csv")
    options_path = ROOT / config.get("options_data", "data/options_5m.csv")

    if not underlying_path.exists() or not options_path.exists():
        return {
            "strategy": config.get("name", "unknown"),
            "status": "missing_data",
            "underlying_data": str(underlying_path),
            "options_data": str(options_path),
            "trades": 0,
            "net_pnl": 0.0,
            "max_drawdown": 0.0,
            "win_rate": 0.0,
        }

    under, opt, _ = load_market_data(config)
    return run_backtest_preloaded(config, under, opt)

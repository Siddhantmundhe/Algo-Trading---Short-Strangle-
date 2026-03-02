from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from dotenv import dotenv_values
from kiteconnect import KiteConnect

import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.strategies.short_strangle import select_leg


@dataclass
class Leg:
    option_type: str
    symbol: str
    strike: float
    entry_price: float
    sl_price: float
    is_open: bool = True
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None


def now_ist() -> pd.Timestamp:
    return pd.Timestamp.now(tz="Asia/Kolkata")


def parse_hhmm(hhmm: str) -> Tuple[int, int]:
    h, m = hhmm.split(":")
    return int(h), int(m)


def today_at(hhmm: str, ref: Optional[pd.Timestamp] = None) -> pd.Timestamp:
    ref = ref or now_ist()
    h, m = parse_hhmm(hhmm)
    return ref.normalize() + pd.Timedelta(hours=h, minutes=m)


def in_window(ts: pd.Timestamp, start_hhmm: str, end_hhmm: str) -> bool:
    return today_at(start_hhmm, ts) <= ts <= today_at(end_hhmm, ts)


def load_config(path: str | Path) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def resolve_token_path(explicit: Optional[str]) -> Optional[Path]:
    if explicit:
        p = Path(explicit)
        if p.exists():
            return p
    candidates = [
        ROOT / "broker" / "access_token.txt",
        ROOT.parent / "kite-login" / "broker" / "access_token.txt",
        ROOT.parent / "pivot-point-strat" / "broker" / "access_token.txt",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def load_kite(token_path: Optional[str]) -> KiteConnect:
    vals = dotenv_values(ROOT / ".env")
    api_key = (vals.get("KITE_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("Missing KITE_API_KEY in .env")

    access_token = (vals.get("KITE_ACCESS_TOKEN") or "").strip()
    if not access_token:
        tpath = resolve_token_path(token_path)
        if tpath is None:
            raise RuntimeError("No access token found. Provide --token-path or set KITE_ACCESS_TOKEN.")
        access_token = tpath.read_text(encoding="utf-8").strip()
        if not access_token:
            raise RuntimeError(f"Access token file is empty: {tpath}")

    kite = KiteConnect(api_key=api_key)
    kite.set_access_token(access_token)
    p = kite.profile()
    print(f"Auth OK | {p.get('user_name') or p.get('user_id')}")
    return kite


def find_nearest_future_token(nfo: pd.DataFrame, index_name: str, ref_date: datetime) -> Tuple[int, str]:
    fut = nfo[
        (nfo["segment"].astype(str).str.upper() == "NFO-FUT")
        & (nfo["name"].astype(str).str.upper() == index_name.upper())
    ].copy()
    fut["expiry"] = pd.to_datetime(fut["expiry"], errors="coerce")
    fut = fut.dropna(subset=["expiry"])
    fut = fut[fut["expiry"].dt.date >= ref_date.date()].sort_values("expiry")
    if fut.empty:
        raise RuntimeError(f"No active future found for {index_name}")
    row = fut.iloc[0]
    return int(row["instrument_token"]), str(row["tradingsymbol"])


def get_underlying_ltp(kite: KiteConnect, fut_symbol: str) -> float:
    q = kite.quote([f"NFO:{fut_symbol}"])
    return float(q[f"NFO:{fut_symbol}"]["last_price"])


def fetch_underlying_intraday(kite: KiteConnect, token: int, interval: str) -> pd.DataFrame:
    now = now_ist()
    start = now.normalize() + pd.Timedelta(hours=9, minutes=0)
    rows = kite.historical_data(
        instrument_token=token,
        from_date=start.to_pydatetime(),
        to_date=now.to_pydatetime(),
        interval=interval,
        continuous=False,
        oi=False,
    )
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["datetime"] = pd.to_datetime(df["date"], errors="coerce")
    return df.dropna(subset=["datetime"]).sort_values("datetime").reset_index(drop=True)


def build_entry_snapshot(
    kite: KiteConnect,
    nfo: pd.DataFrame,
    index_name: str,
    expiry: datetime.date,
    underlying_price: float,
    strike_step: int,
    strike_span_steps: int,
) -> pd.DataFrame:
    atm = int(round(float(underlying_price) / float(strike_step)) * strike_step)
    min_strike = atm - strike_step * int(strike_span_steps)
    max_strike = atm + strike_step * int(strike_span_steps)

    opt = nfo[
        (nfo["segment"].astype(str).str.upper() == "NFO-OPT")
        & (nfo["name"].astype(str).str.upper() == index_name.upper())
    ].copy()
    opt["expiry"] = pd.to_datetime(opt["expiry"], errors="coerce").dt.date
    opt["strike"] = pd.to_numeric(opt["strike"], errors="coerce")
    opt = opt.dropna(subset=["expiry", "strike"])
    opt = opt[
        (opt["expiry"] == expiry)
        & (opt["strike"] >= float(min_strike))
        & (opt["strike"] <= float(max_strike))
        & (opt["instrument_type"].astype(str).str.upper().isin(["CE", "PE"]))
    ].copy()
    if opt.empty:
        return pd.DataFrame()

    symbols = opt["tradingsymbol"].astype(str).tolist()
    quote_keys = [f"NFO:{s}" for s in symbols]
    quotes = kite.quote(quote_keys)

    rows: List[Dict[str, Any]] = []
    for _, r in opt.iterrows():
        sym = str(r["tradingsymbol"])
        q = quotes.get(f"NFO:{sym}", {})
        ltp = q.get("last_price")
        if ltp is None:
            continue
        rows.append(
            {
                "symbol": sym,
                "expiry": r["expiry"],
                "strike": float(r["strike"]),
                "option_type": str(r["instrument_type"]).upper(),
                "close": float(ltp),
            }
        )
    return pd.DataFrame(rows)


def pick_expiry(nfo: pd.DataFrame, index_name: str, trade_day: datetime.date) -> Optional[datetime.date]:
    opt = nfo[
        (nfo["segment"].astype(str).str.upper() == "NFO-OPT")
        & (nfo["name"].astype(str).str.upper() == index_name.upper())
    ].copy()
    opt["expiry"] = pd.to_datetime(opt["expiry"], errors="coerce").dt.date
    opt = opt.dropna(subset=["expiry"])
    exp = sorted([d for d in opt["expiry"].unique().tolist() if d >= trade_day])
    return exp[0] if exp else None


def append_csv(path: Path, row: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame([row])
    df.to_csv(path, mode="a", index=False, header=not path.exists())


def calc_costs(cfg: Dict[str, Any]) -> float:
    lots = int(cfg.get("lots", 1))
    slip = float(cfg.get("slippage_per_order_rupees", 5.0))
    charge = float(cfg.get("charges_per_lot_roundtrip_rupees", 40.0))
    return (slip * 4.0 + charge * 2.0) * max(1, lots)


def leg_realized(leg: Leg, qty: int) -> float:
    if leg.exit_price is None:
        return 0.0
    return (leg.entry_price - float(leg.exit_price)) * qty


def main() -> None:
    parser = argparse.ArgumentParser(description="Paper live runner for short strangle")
    parser.add_argument("--config", default="configs/live/strangle_live_top2.json")
    parser.add_argument("--token-path", default=None)
    args = parser.parse_args()

    cfg = load_config(args.config)
    kite = load_kite(args.token_path)
    nfo = pd.DataFrame(kite.instruments("NFO"))
    index_name = str(cfg.get("index", "NIFTY")).upper()
    interval = str(cfg.get("interval", "5minute"))

    fut_token, fut_symbol = find_nearest_future_token(nfo, index_name, now_ist().to_pydatetime())
    print(f"Using future: {fut_symbol} ({fut_token})")

    entry_time = str(cfg.get("entry_time", "09:20"))
    exit_time = str(cfg.get("exit_time", "15:20"))
    market_start = str(cfg.get("market_start", "09:15"))
    market_end = str(cfg.get("market_end", "15:30"))
    poll_sec = int(cfg.get("poll_every_seconds", 20))
    strike_span_steps = int(cfg.get("strike_span_steps", 12))
    max_trades = int(cfg.get("max_trades_per_day", 1))
    max_daily_loss = float(cfg.get("max_daily_loss_rupees", 3000))
    out_csv = ROOT / "reports" / str(cfg.get("live_output_name", "live_strangle_paper_trades.csv"))

    trade_day: Optional[str] = None
    last_entry_candle: Optional[pd.Timestamp] = None
    trades_today = 0
    closed_pnl = 0.0
    open_trade: Optional[Dict[str, Any]] = None

    print("Running paper strangle loop. Press Ctrl+C to stop.")
    while True:
        now = now_ist()
        day = str(now.date())
        if trade_day != day:
            trade_day = day
            last_entry_candle = None
            trades_today = 0
            closed_pnl = 0.0
            open_trade = None
            print(f"New day: {trade_day}")

        if not in_window(now, market_start, market_end):
            time.sleep(poll_sec)
            continue

        try:
            # Update open trade first
            if open_trade is not None:
                ce: Leg = open_trade["ce"]
                pe: Leg = open_trade["pe"]
                lot_size = int(open_trade["lot_size"])
                qty = int(open_trade["qty"])
                q = kite.quote([f"NFO:{ce.symbol}", f"NFO:{pe.symbol}"])
                ce_ltp = float(q[f"NFO:{ce.symbol}"]["last_price"])
                pe_ltp = float(q[f"NFO:{pe.symbol}"]["last_price"])

                if ce.is_open and ce_ltp >= ce.sl_price:
                    ce.is_open = False
                    ce.exit_price = ce.sl_price
                    ce.exit_reason = "LEG_SL"
                if pe.is_open and pe_ltp >= pe.sl_price:
                    pe.is_open = False
                    pe.exit_price = pe.sl_price
                    pe.exit_reason = "LEG_SL"

                mtm = leg_realized(ce, qty) + leg_realized(pe, qty)
                if ce.is_open:
                    mtm += (ce.entry_price - ce_ltp) * qty
                if pe.is_open:
                    mtm += (pe.entry_price - pe_ltp) * qty

                sl_hit = mtm <= -abs(float(cfg.get("combined_mtm_sl_rupees", 3000)))
                tgt_hit = mtm >= abs(float(cfg.get("combined_mtm_target_rupees", 2500)))
                eod_hit = now >= today_at(exit_time, now)
                close_reason = None
                if sl_hit:
                    close_reason = "COMBINED_SL"
                elif tgt_hit:
                    close_reason = "COMBINED_TGT"
                elif eod_hit:
                    close_reason = "EOD"

                if close_reason is not None:
                    if ce.is_open:
                        ce.is_open = False
                        ce.exit_price = ce_ltp
                        ce.exit_reason = close_reason
                    if pe.is_open:
                        pe.is_open = False
                        pe.exit_price = pe_ltp
                        pe.exit_reason = close_reason

                if not ce.is_open and not pe.is_open:
                    gross = leg_realized(ce, qty) + leg_realized(pe, qty)
                    costs = calc_costs(cfg)
                    net = gross - costs
                    closed_pnl += net
                    row = {
                        "trade_date": day,
                        "entry_time": str(open_trade["entry_ts"]),
                        "exit_time": str(now),
                        "expiry": str(open_trade["expiry"]),
                        "ce_symbol": ce.symbol,
                        "pe_symbol": pe.symbol,
                        "ce_strike": ce.strike,
                        "pe_strike": pe.strike,
                        "ce_entry": ce.entry_price,
                        "pe_entry": pe.entry_price,
                        "ce_exit": ce.exit_price,
                        "pe_exit": pe.exit_price,
                        "ce_exit_reason": ce.exit_reason,
                        "pe_exit_reason": pe.exit_reason,
                        "gross_pnl_rupees": gross,
                        "costs_rupees": costs,
                        "net_pnl_rupees": net,
                        "combined_exit_reason": close_reason or "CLOSED",
                    }
                    append_csv(out_csv, row)
                    print(
                        f"CLOSED | net={net:.2f} gross={gross:.2f} ce={ce.exit_reason} pe={pe.exit_reason} "
                        f"running_day_pnl={closed_pnl:.2f}"
                    )
                    open_trade = None

            # Entry logic
            if open_trade is None and trades_today < max_trades and closed_pnl > -abs(max_daily_loss):
                under = fetch_underlying_intraday(kite, fut_token, interval)
                if len(under) >= 2:
                    latest = pd.to_datetime(under.iloc[-2]["datetime"])
                    if last_entry_candle is None or latest > last_entry_candle:
                        if latest.hour == parse_hhmm(entry_time)[0] and latest.minute == parse_hhmm(entry_time)[1]:
                            trade_date = latest.date()
                            expiry = pick_expiry(nfo, index_name, trade_date)
                            if expiry is not None:
                                underlying_price = float(under.iloc[-2]["close"])
                                snapshot = build_entry_snapshot(
                                    kite=kite,
                                    nfo=nfo,
                                    index_name=index_name,
                                    expiry=expiry,
                                    underlying_price=underlying_price,
                                    strike_step=int(cfg.get("strike_step", 50)),
                                    strike_span_steps=strike_span_steps,
                                )
                                if not snapshot.empty:
                                    method = str(cfg.get("strike_method", "delta_target")).lower()
                                    ce_sel = select_leg(
                                        options_snapshot=snapshot,
                                        option_type="CE",
                                        strike_method=method,
                                        underlying_price=underlying_price,
                                        step=int(cfg.get("strike_step", 50)),
                                        premium_target=float(cfg.get("premium_target_per_leg", 60)),
                                        premium_band=float(cfg.get("premium_band", 20)),
                                        fixed_distance_points=int(cfg.get("fixed_distance_points", 300)),
                                        target_delta=float(cfg.get("target_delta_ce", 0.15)),
                                    )
                                    pe_sel = select_leg(
                                        options_snapshot=snapshot,
                                        option_type="PE",
                                        strike_method=method,
                                        underlying_price=underlying_price,
                                        step=int(cfg.get("strike_step", 50)),
                                        premium_target=float(cfg.get("premium_target_per_leg", 60)),
                                        premium_band=float(cfg.get("premium_band", 20)),
                                        fixed_distance_points=int(cfg.get("fixed_distance_points", 300)),
                                        target_delta=float(cfg.get("target_delta_pe", -0.15)),
                                    )
                                    if ce_sel and pe_sel and ce_sel.symbol and pe_sel.symbol:
                                        q = kite.quote([f"NFO:{ce_sel.symbol}", f"NFO:{pe_sel.symbol}"])
                                        ce_entry = float(q[f"NFO:{ce_sel.symbol}"]["last_price"])
                                        pe_entry = float(q[f"NFO:{pe_sel.symbol}"]["last_price"])
                                        sl_pct = float(cfg.get("per_leg_sl_pct", 30))
                                        ce_leg = Leg("CE", ce_sel.symbol, ce_sel.strike, ce_entry, ce_entry * (1 + sl_pct / 100.0))
                                        pe_leg = Leg("PE", pe_sel.symbol, pe_sel.strike, pe_entry, pe_entry * (1 + sl_pct / 100.0))
                                        lot_size = int(cfg.get("lot_size", 50))
                                        lots = int(cfg.get("lots", 1))
                                        open_trade = {
                                            "entry_ts": now,
                                            "expiry": expiry,
                                            "ce": ce_leg,
                                            "pe": pe_leg,
                                            "lot_size": lot_size,
                                            "qty": lot_size * max(1, lots),
                                        }
                                        trades_today += 1
                                        print(
                                            f"OPEN | ce={ce_leg.symbol}@{ce_entry:.2f} pe={pe_leg.symbol}@{pe_entry:.2f} "
                                            f"sl_pct={sl_pct:.1f} expiry={expiry}"
                                        )
                            last_entry_candle = latest

        except KeyboardInterrupt:
            print("Stopped by user.")
            break
        except Exception as e:
            print(f"[loop_error] {e}")

        time.sleep(poll_sec)


if __name__ == "__main__":
    main()

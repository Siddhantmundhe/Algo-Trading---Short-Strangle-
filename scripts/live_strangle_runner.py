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
    entry_order_id: Optional[str] = None
    exit_order_id: Optional[str] = None
    entry_fill_source: str = "ltp"
    exit_fill_source: str = "ltp"


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


def place_option_market_order(
    kite: KiteConnect,
    symbol: str,
    side: str,
    qty: int,
    product: str,
) -> str:
    tx = str(side).upper()
    if tx not in ("BUY", "SELL"):
        raise ValueError(f"Invalid side: {side}")

    order_id = kite.place_order(
        variety="regular",
        exchange="NFO",
        tradingsymbol=symbol,
        transaction_type=tx,
        quantity=int(qty),
        order_type="MARKET",
        product=str(product).upper(),
        validity="DAY",
    )
    return str(order_id)


def reconcile_order_fill_price(
    kite: KiteConnect,
    order_id: str,
    fallback_price: float,
    retries: int = 4,
    sleep_seconds: float = 0.8,
) -> Tuple[float, str]:
    """
    Reconcile executed price using orderbook/trades.
    Returns (price, source).
    """
    oid = str(order_id)
    for _ in range(max(1, int(retries))):
        try:
            hist = kite.order_history(oid)
            if hist:
                last = hist[-1]
                status = str(last.get("status", "")).upper()
                avg_px = float(last.get("average_price") or 0.0)
                if status == "COMPLETE" and avg_px > 0:
                    return avg_px, "order_history"
        except Exception:
            pass

        try:
            trades = kite.order_trades(oid)
            if trades:
                total_qty = 0
                weighted = 0.0
                for t in trades:
                    q = int(t.get("filled_quantity") or t.get("quantity") or 0)
                    px = float(t.get("average_price") or t.get("fill_price") or 0.0)
                    if q > 0 and px > 0:
                        total_qty += q
                        weighted += q * px
                if total_qty > 0:
                    return weighted / total_qty, "order_trades"
        except Exception:
            pass

        time.sleep(float(sleep_seconds))

    return float(fallback_price), "ltp_fallback"


def get_ltp_map(kite: KiteConnect, symbols: List[str]) -> Dict[str, float]:
    keys = [f"NFO:{s}" for s in symbols]
    q = kite.quote(keys)
    out: Dict[str, float] = {}
    for s in symbols:
        out[s] = float(q[f"NFO:{s}"]["last_price"])
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Live/Paper runner for short strangle")
    parser.add_argument("--config", default="configs/live/strangle_live_top2.json")
    parser.add_argument("--token-path", default=None)
    parser.add_argument("--mode", choices=["paper", "live"], default=None)
    parser.add_argument("--confirm-live", default=None, help="Required phrase to enable live mode")
    args = parser.parse_args()

    cfg = load_config(args.config)
    mode = str(args.mode or cfg.get("execution_mode", "paper")).lower()
    if mode not in ("paper", "live"):
        raise RuntimeError("execution_mode must be paper or live")

    if mode == "live":
        require_confirm = bool(cfg.get("live_require_confirm", True))
        confirm_phrase = str(cfg.get("live_confirm_phrase", "YES_LIVE"))
        if require_confirm and str(args.confirm_live or "") != confirm_phrase:
            raise RuntimeError(
                f"Live mode blocked. Re-run with --confirm-live {confirm_phrase}"
            )

    kite = load_kite(args.token_path)
    nfo = pd.DataFrame(kite.instruments("NFO"))
    index_name = str(cfg.get("index", "NIFTY")).upper()
    interval = str(cfg.get("interval", "5minute"))
    live_product = str(cfg.get("live_product", "MIS")).upper()

    fut_token, fut_symbol = find_nearest_future_token(nfo, index_name, now_ist().to_pydatetime())
    print(f"Mode={mode.upper()} | Using future: {fut_symbol} ({fut_token})")

    entry_time = str(cfg.get("entry_time", "09:20"))
    exit_time = str(cfg.get("exit_time", "15:20"))
    market_start = str(cfg.get("market_start", "09:15"))
    market_end = str(cfg.get("market_end", "15:30"))
    poll_sec = int(cfg.get("poll_every_seconds", 20))
    strike_span_steps = int(cfg.get("strike_span_steps", 12))
    max_trades = int(cfg.get("max_trades_per_day", 1))
    max_daily_loss = float(cfg.get("max_daily_loss_rupees", 3000))
    max_consecutive_losses = int(cfg.get("max_consecutive_losses", 2))

    out_default = "live_strangle_live_trades.csv" if mode == "live" else "live_strangle_paper_trades.csv"
    out_csv = ROOT / "reports" / str(cfg.get("live_output_name", out_default))

    trade_day: Optional[str] = None
    last_entry_candle: Optional[pd.Timestamp] = None
    trades_today = 0
    closed_pnl = 0.0
    consecutive_losses = 0
    halt_entries = False
    open_trade: Optional[Dict[str, Any]] = None

    print("Running strangle loop. Press Ctrl+C to stop.")
    while True:
        now = now_ist()
        day = str(now.date())
        if trade_day != day:
            trade_day = day
            last_entry_candle = None
            trades_today = 0
            closed_pnl = 0.0
            consecutive_losses = 0
            halt_entries = False
            open_trade = None
            print(f"New day: {trade_day}")

        if not in_window(now, market_start, market_end):
            time.sleep(poll_sec)
            continue

        try:
            if open_trade is not None:
                ce: Leg = open_trade["ce"]
                pe: Leg = open_trade["pe"]
                qty = int(open_trade["qty"])

                ltp_map = get_ltp_map(kite, [ce.symbol, pe.symbol])
                ce_ltp = float(ltp_map[ce.symbol])
                pe_ltp = float(ltp_map[pe.symbol])

                if ce.is_open and ce_ltp >= ce.sl_price:
                    ce.exit_reason = "LEG_SL"
                if pe.is_open and pe_ltp >= pe.sl_price:
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
                    if ce.is_open and ce.exit_reason is None:
                        ce.exit_reason = close_reason
                    if pe.is_open and pe.exit_reason is None:
                        pe.exit_reason = close_reason

                for leg, ltp in [(ce, ce_ltp), (pe, pe_ltp)]:
                    if leg.is_open and leg.exit_reason is not None:
                        if mode == "live":
                            try:
                                oid = place_option_market_order(
                                    kite=kite,
                                    symbol=leg.symbol,
                                    side="BUY",
                                    qty=qty,
                                    product=live_product,
                                )
                                leg.exit_order_id = oid
                                px, src = reconcile_order_fill_price(kite, oid, ltp)
                                leg.exit_price = float(px)
                                leg.exit_fill_source = src
                            except Exception as e:
                                print(f"[exit_order_error] {leg.symbol}: {e}")
                                continue
                        leg.is_open = False
                        if mode != "live":
                            leg.exit_price = float(ltp)
                            leg.exit_fill_source = "ltp"

                if not ce.is_open and not pe.is_open:
                    gross = leg_realized(ce, qty) + leg_realized(pe, qty)
                    costs = calc_costs(cfg)
                    net = gross - costs
                    closed_pnl += net
                    if net < 0:
                        consecutive_losses += 1
                    else:
                        consecutive_losses = 0

                    if closed_pnl <= -abs(max_daily_loss):
                        halt_entries = True
                    if consecutive_losses >= max(1, max_consecutive_losses):
                        halt_entries = True

                    row = {
                        "execution_mode": mode,
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
                        "ce_entry_order_id": ce.entry_order_id,
                        "pe_entry_order_id": pe.entry_order_id,
                        "ce_exit_order_id": ce.exit_order_id,
                        "pe_exit_order_id": pe.exit_order_id,
                        "ce_entry_fill_source": ce.entry_fill_source,
                        "pe_entry_fill_source": pe.entry_fill_source,
                        "ce_exit_fill_source": ce.exit_fill_source,
                        "pe_exit_fill_source": pe.exit_fill_source,
                        "ce_exit_reason": ce.exit_reason,
                        "pe_exit_reason": pe.exit_reason,
                        "gross_pnl_rupees": gross,
                        "costs_rupees": costs,
                        "net_pnl_rupees": net,
                        "combined_exit_reason": close_reason or "CLOSED",
                        "consecutive_losses": consecutive_losses,
                        "halt_entries": halt_entries,
                    }
                    append_csv(out_csv, row)
                    print(
                        f"CLOSED | mode={mode} net={net:.2f} gross={gross:.2f} "
                        f"ce={ce.exit_reason} pe={pe.exit_reason} day_pnl={closed_pnl:.2f} "
                        f"loss_streak={consecutive_losses} halt={halt_entries}"
                    )
                    open_trade = None

            if open_trade is None and (not halt_entries) and trades_today < max_trades and closed_pnl > -abs(max_daily_loss):
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
                                        lot_size = int(cfg.get("lot_size", 50))
                                        lots = int(cfg.get("lots", 1))
                                        qty = lot_size * max(1, lots)

                                        ltp_map = get_ltp_map(kite, [ce_sel.symbol, pe_sel.symbol])
                                        ce_entry = float(ltp_map[ce_sel.symbol])
                                        pe_entry = float(ltp_map[pe_sel.symbol])
                                        sl_pct = float(cfg.get("per_leg_sl_pct", 30))

                                        ce_leg = Leg("CE", ce_sel.symbol, ce_sel.strike, ce_entry, ce_entry * (1 + sl_pct / 100.0))
                                        pe_leg = Leg("PE", pe_sel.symbol, pe_sel.strike, pe_entry, pe_entry * (1 + sl_pct / 100.0))

                                        if mode == "live":
                                            ce_oid = None
                                            pe_oid = None
                                            try:
                                                ce_oid = place_option_market_order(
                                                    kite=kite,
                                                    symbol=ce_leg.symbol,
                                                    side="SELL",
                                                    qty=qty,
                                                    product=live_product,
                                                )
                                                ce_leg.entry_order_id = ce_oid
                                                ce_px, ce_src = reconcile_order_fill_price(kite, ce_oid, ce_entry)
                                                ce_leg.entry_price = float(ce_px)
                                                ce_leg.entry_fill_source = ce_src
                                                ce_leg.sl_price = ce_leg.entry_price * (1 + sl_pct / 100.0)

                                                pe_oid = place_option_market_order(
                                                    kite=kite,
                                                    symbol=pe_leg.symbol,
                                                    side="SELL",
                                                    qty=qty,
                                                    product=live_product,
                                                )
                                                pe_leg.entry_order_id = pe_oid
                                                pe_px, pe_src = reconcile_order_fill_price(kite, pe_oid, pe_entry)
                                                pe_leg.entry_price = float(pe_px)
                                                pe_leg.entry_fill_source = pe_src
                                                pe_leg.sl_price = pe_leg.entry_price * (1 + sl_pct / 100.0)
                                            except Exception as e:
                                                print(f"[entry_order_error] {e}")
                                                if ce_oid and not pe_oid:
                                                    try:
                                                        place_option_market_order(
                                                            kite=kite,
                                                            symbol=ce_leg.symbol,
                                                            side="BUY",
                                                            qty=qty,
                                                            product=live_product,
                                                        )
                                                        print("Rolled back CE entry due to partial fill scenario.")
                                                    except Exception as rollback_e:
                                                        print(f"[rollback_error] {rollback_e}")
                                                last_entry_candle = latest
                                                time.sleep(poll_sec)
                                                continue

                                        open_trade = {
                                            "entry_ts": now,
                                            "expiry": expiry,
                                            "ce": ce_leg,
                                            "pe": pe_leg,
                                            "lot_size": lot_size,
                                            "qty": qty,
                                        }
                                        trades_today += 1
                                        print(
                                            f"OPEN | mode={mode} ce={ce_leg.symbol}@{ce_entry:.2f} "
                                            f"pe={pe_leg.symbol}@{pe_entry:.2f} sl_pct={sl_pct:.1f} expiry={expiry}"
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

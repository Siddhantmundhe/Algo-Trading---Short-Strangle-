from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from dotenv import dotenv_values
from kiteconnect import KiteConnect

ROOT = Path(__file__).resolve().parent.parent


def now_ist() -> pd.Timestamp:
    return pd.Timestamp.now(tz="Asia/Kolkata")


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
    return kite


def find_nearest_future(nfo: pd.DataFrame, index_name: str, ref_date: datetime) -> Optional[pd.Series]:
    fut = nfo[
        (nfo["segment"].astype(str).str.upper() == "NFO-FUT")
        & (nfo["name"].astype(str).str.upper() == index_name.upper())
    ].copy()
    fut["expiry"] = pd.to_datetime(fut["expiry"], errors="coerce")
    fut = fut.dropna(subset=["expiry"])
    fut = fut[fut["expiry"].dt.date >= ref_date.date()].sort_values("expiry")
    if fut.empty:
        return None
    return fut.iloc[0]


def pick_expiry(nfo: pd.DataFrame, index_name: str, trade_day: datetime.date) -> Optional[datetime.date]:
    opt = nfo[
        (nfo["segment"].astype(str).str.upper() == "NFO-OPT")
        & (nfo["name"].astype(str).str.upper() == index_name.upper())
    ].copy()
    opt["expiry"] = pd.to_datetime(opt["expiry"], errors="coerce").dt.date
    opt = opt.dropna(subset=["expiry"])
    exp = sorted([d for d in opt["expiry"].unique().tolist() if d >= trade_day])
    return exp[0] if exp else None


def check_output_path(path: Path) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        test_file = path.parent / ".write_test.tmp"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Pre-open health checks for strangle runner")
    parser.add_argument("--config", default="configs/live/strangle_live_nifty_orders_v1.json")
    parser.add_argument("--token-path", default=None)
    args = parser.parse_args()

    cfg = load_config(args.config)
    index_name = str(cfg.get("index", "NIFTY")).upper()

    checks: List[Dict[str, Any]] = []

    try:
        kite = load_kite(args.token_path)
        profile = kite.profile()
        checks.append({"check": "auth_profile", "ok": True, "detail": profile.get("user_id")})
    except Exception as e:
        checks.append({"check": "auth_profile", "ok": False, "detail": str(e)})
        kite = None

    nfo = pd.DataFrame()
    if kite is not None:
        try:
            nfo = pd.DataFrame(kite.instruments("NFO"))
            checks.append({"check": "nfo_instruments", "ok": len(nfo) > 0, "detail": f"rows={len(nfo)}"})
        except Exception as e:
            checks.append({"check": "nfo_instruments", "ok": False, "detail": str(e)})

    if not nfo.empty:
        fut = find_nearest_future(nfo, index_name, now_ist().to_pydatetime())
        checks.append({
            "check": "nearest_future",
            "ok": fut is not None,
            "detail": str(fut.get("tradingsymbol")) if fut is not None else "not_found",
        })

        exp = pick_expiry(nfo, index_name, now_ist().date())
        checks.append({"check": "nearest_option_expiry", "ok": exp is not None, "detail": str(exp)})

    out_csv = ROOT / "reports" / str(cfg.get("live_output_name", "live/live_strangle_live_trades.csv"))
    checks.append({"check": "output_path_writable", "ok": check_output_path(out_csv), "detail": str(out_csv)})

    ts = now_ist()
    checks.append({"check": "clock_ist", "ok": True, "detail": str(ts)})

    if kite is not None:
        try:
            m = kite.margins()
            checks.append({"check": "margins_api", "ok": True, "detail": "available" if m else "empty"})
        except Exception as e:
            checks.append({"check": "margins_api", "ok": False, "detail": str(e)})

    print("Pre-open healthcheck:")
    any_fail = False
    for c in checks:
        status = "OK" if c["ok"] else "FAIL"
        if not c["ok"]:
            any_fail = True
        print(f"- {status:4} | {c['check']}: {c['detail']}")

    if any_fail:
        raise SystemExit(2)

    print("All checks passed.")


if __name__ == "__main__":
    main()

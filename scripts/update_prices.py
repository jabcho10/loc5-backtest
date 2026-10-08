"""Fetch recent daily closes for SOXL/TQQQ and merge them into prices.json.

Closes are split-adjusted but not dividend-adjusted (auto_adjust=False), which
matches the prices LOC orders are actually placed at. Today's bar is dropped
while the US session is still open so a partial close never lands in the file.
"""
import json, sys, time
from datetime import datetime, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

import yfinance as yf

TICKERS = ["SOXL", "TQQQ"]
KEEP = 300  # trading days kept per ticker
OUT = Path(__file__).resolve().parent.parent / "prices.json"
NY = ZoneInfo("America/New_York")


def fetch(tries=3):
    for k in range(tries):
        try:
            df = yf.download(TICKERS, period="3mo", interval="1d", auto_adjust=False, progress=False)
            if not df.empty:
                return df["Close"]
        except Exception as e:  # network hiccups on shared runners
            print("fetch failed:", e, file=sys.stderr)
        time.sleep(10 * (k + 1))
    return None


def main():
    old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {"prices": {}}
    close = fetch()
    if close is None:
        print("no data; keeping existing prices.json")
        return
    now = datetime.now(NY)
    session_open = now.weekday() < 5 and now.time() < dtime(16, 15)
    prices = dict(old.get("prices", {}))
    for t in TICKERS:
        merged = {d: c for d, c in prices.get(t, [])}
        for ts, c in close[t].dropna().items():
            d = ts.strftime("%Y-%m-%d")
            if session_open and d == now.strftime("%Y-%m-%d"):
                continue
            merged[d] = round(float(c), 4)
        prices[t] = [list(x) for x in sorted(merged.items())[-KEEP:]]
    if OUT.exists() and prices == old.get("prices"):
        print("unchanged")
        return
    OUT.write_text(json.dumps({"updated": now.strftime("%Y-%m-%d %H:%M %Z"), "prices": prices},
                              separators=(",", ":")), encoding="utf-8")
    print("updated", {t: prices[t][-1] for t in TICKERS})


if __name__ == "__main__":
    main()

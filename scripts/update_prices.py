"""Fetch recent daily closes for SOXL/TQQQ and merge them into prices.json.

Two sources, fetched per ticker so one failure never blocks the other:
  1. Yahoo  - chart API directly (query1, then query2), yfinance as a last resort.
              Covers 2y, so every kept close is re-adjusted for splits on each run.
  2. Google - Finance quote page, whose embedded daily bars cover the last month.
              Fills in any day Yahoo has not published yet, whichever is first.
Closes are split-adjusted but not dividend-adjusted, which matches the prices LOC
orders are actually placed at. Today's bar is dropped until the closing auction
has printed, so a partial close never lands in the file.
"""
import json, re, sys, time
import urllib.request
from datetime import datetime, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

TICKERS = {"SOXL": "NYSEARCA", "TQQQ": "NASDAQ"}  # ticker -> Google exchange code
KEEP = 300  # trading days kept per ticker
OUT = Path(__file__).resolve().parent.parent / "prices.json"
NY = ZoneInfo("America/New_York")
CLOSED_AFTER = dtime(16, 10)  # closing auction prints by ~16:01 ET; leave a margin
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
      "Accept-Language": "en-US,en;q=0.9"}


def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8")


def retry(fn, *args, tries=3):
    for k in range(tries):
        try:
            out = fn(*args)
            if out:
                return out
        except Exception as e:  # network hiccups on shared runners
            print(f"  {fn.__name__}{args} failed: {e}", file=sys.stderr)
        time.sleep(3 * (k + 1))
    return {}


def yahoo_chart(t, host):
    j = json.loads(get(f"https://{host}.finance.yahoo.com/v8/finance/chart/{t}?range=2y&interval=1d"))
    res = j["chart"]["result"][0]
    closes = res["indicators"]["quote"][0]["close"]
    return {datetime.fromtimestamp(ts, NY).strftime("%Y-%m-%d"): round(c, 4)
            for ts, c in zip(res["timestamp"], closes) if c is not None}


def yahoo_yf(t):
    import yfinance as yf
    df = yf.Ticker(t).history(period="2y", interval="1d", auto_adjust=False)
    return {ts.strftime("%Y-%m-%d"): round(float(c), 4) for ts, c in df["Close"].dropna().items()}


def yahoo(t):
    for host in ("query1", "query2"):
        out = retry(yahoo_chart, t, host, tries=2)
        if out:
            return out
    return retry(yahoo_yf, t, tries=2)


def google(t, ex):
    html = get(f"https://www.google.com/finance/quote/{t}:{ex}")
    # daily bars embedded as [open, close, high, low, "YYYY-MM-DDTHH:MM:SS-04:00", volume]
    bars = re.findall(r'\[[\d.]+,([\d.]+),[\d.]+,[\d.]+,"(\d{4}-\d\d-\d\d)T[\d:]+[-+]\d\d:\d\d",\d+\]', html)
    return {d: round(float(c), 4) for c, d in bars}


def main():
    old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {"prices": {}}
    now = datetime.now(NY)
    today = now.strftime("%Y-%m-%d")
    session_open = now.weekday() < 5 and now.time() < CLOSED_AFTER
    prices = dict(old.get("prices", {}))
    missing = []
    for t, ex in TICKERS.items():
        y, g = yahoo(t), retry(google, t, ex)
        if session_open:
            y.pop(today, None)
            g.pop(today, None)
        merged = {d: c for d, c in prices.get(t, [])}
        merged.update(y)  # Yahoo is canonical (full split-adjusted history)
        last_y = max(y) if y else ""
        extra = {d: c for d, c in g.items() if d > last_y and (y or d not in merged)}
        merged.update(extra)
        for d in set(y) & set(g):
            if abs(y[d] - g[d]) > 0.01 * y[d]:
                print(f"::warning::{t} {d}: yahoo {y[d]} vs google {g[d]}")
        if not y and not g:
            missing.append(t)
        print(f"{t}: yahoo last {last_y or '-'}, google last {max(g) if g else '-'}"
              + (f", google filled {sorted(extra)}" if extra else ""))
        prices[t] = [list(x) for x in sorted(merged.items())[-KEEP:]]
    if missing:
        print(f"::warning::no data from either source for {missing}; kept existing closes")
    if OUT.exists() and prices == old.get("prices"):
        print("unchanged")
        return
    OUT.write_text(json.dumps({"updated": now.strftime("%Y-%m-%d %H:%M %Z"), "prices": prices},
                              separators=(",", ":")), encoding="utf-8")
    print("updated", {t: prices[t][-1] for t in TICKERS})


if __name__ == "__main__":
    main()

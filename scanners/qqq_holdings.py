"""
scanners/qqq_holdings.py
Fetches the current Nasdaq-100 (QQQ) constituents.

Strategy (tries in order):
  1. yfinance ETF holdings via QQQ ticker info
  2. Wikipedia Nasdaq-100 page (most reliable fallback)
  3. Hardcoded snapshot (last resort, may be stale)

Results are cached to data/qqq_holdings_cache.json (TTL: 24 hrs).
"""

import json
import time
from pathlib import Path

CACHE_PATH = Path("data/qqq_holdings_cache.json")
CACHE_TTL  = 86_400   # 24 hours


def get_qqq_holdings(refresh: bool = False) -> list[str]:
    """
    Returns a list of ticker strings for all Nasdaq-100 constituents.
    Tries multiple sources; caches results locally.
    """
    CACHE_PATH.parent.mkdir(exist_ok=True)

    # ── Cache check ───────────────────────────────────────────
    if not refresh and CACHE_PATH.exists():
        try:
            data = json.loads(CACHE_PATH.read_text())
            age  = time.time() - data.get("fetched_at", 0)
            if age < CACHE_TTL:
                tickers = data["tickers"]
                print(f"     [cache] QQQ holdings: {len(tickers)} tickers "
                      f"(age {age/3600:.1f}h)")
                return tickers
        except Exception:
            pass

    tickers = None

    # ── Method 1: yfinance QQQ holdings ──────────────────────
    try:
        import yfinance as yf
        qqq = yf.Ticker("QQQ")
        holdings = qqq.funds_data.top_holdings if hasattr(qqq, 'funds_data') else None
        if holdings is not None and len(holdings) > 50:
            tickers = list(holdings.index)
            print(f"     [yfinance] Fetched {len(tickers)} QQQ holdings")
    except Exception as e:
        print(f"     [yfinance] Failed ({e}), trying Wikipedia...")

    # ── Method 2: Wikipedia Nasdaq-100 page ──────────────────
    if not tickers or len(tickers) < 90:
        try:
            import requests
            from bs4 import BeautifulSoup

            url = "https://en.wikipedia.org/wiki/Nasdaq-100"
            resp = requests.get(url, timeout=15,
                                headers={"User-Agent": "Mozilla/5.0"})
            soup = BeautifulSoup(resp.text, "lxml")

            # The table with id "constituents" or find by caption
            table = soup.find("table", {"id": "constituents"})
            if table is None:
                # Try finding table with "Ticker" header
                for t in soup.find_all("table", class_="wikitable"):
                    headers = [th.get_text(strip=True) for th in t.find_all("th")]
                    if any("Ticker" in h or "Symbol" in h for h in headers):
                        table = t
                        break

            if table:
                rows = table.find_all("tr")[1:]
                parsed = []
                for row in rows:
                    cells = row.find_all(["td", "th"])
                    if len(cells) >= 2:
                        tkr = cells[1].get_text(strip=True)   # usually col 1
                        if 1 <= len(tkr) <= 5 and tkr.isupper():
                            parsed.append(tkr)
                        elif len(cells) >= 1:
                            tkr = cells[0].get_text(strip=True)
                            if 1 <= len(tkr) <= 5 and tkr.replace(".", "").isupper():
                                parsed.append(tkr)

                if len(parsed) > 90:
                    tickers = parsed
                    print(f"     [wikipedia] Fetched {len(tickers)} Nasdaq-100 tickers")
        except Exception as e:
            print(f"     [wikipedia] Failed ({e}), using snapshot...")

    # ── Method 3: Hardcoded snapshot (2025) ──────────────────
    if not tickers or len(tickers) < 90:
        tickers = _HARDCODED_QQQ
        print(f"     [snapshot] Using hardcoded list: {len(tickers)} tickers")

    # ── Clean ─────────────────────────────────────────────────
    # Normalize dots (BRK.B → BRK-B for yfinance)
    tickers = [t.replace(".", "-") for t in tickers]
    tickers = sorted(set(tickers))

    # ── Cache ─────────────────────────────────────────────────
    try:
        CACHE_PATH.write_text(json.dumps({
            "fetched_at": time.time(),
            "tickers":    tickers,
        }, indent=2))
    except Exception:
        pass

    return tickers


# ── Hardcoded snapshot (Nasdaq-100, May 2025) ─────────────────
_HARDCODED_QQQ = [
    "AAPL","MSFT","NVDA","AMZN","META","GOOGL","GOOG","TSLA","AVGO","COST",
    "NFLX","ASML","AMD","PEP","TMUS","QCOM","CSCO","INTU","LIN","AMAT",
    "TXN","ISRG","AMGN","BKNG","CMCSA","MU","VRTX","HON","PANW","ADP",
    "LRCX","SBUX","ADI","REGN","GILD","KLAC","MELI","INTC","CDNS","SNPS",
    "MAR","CEG","MDLZ","CTAS","CRWD","KDP","ORLY","WDAY","FTNT","DXCM",
    "ADSK","MNST","CHTR","CSX","ROP","PCAR","ROST","MRVL","TTD","FAST",
    "IDXX","BIIB","VRSK","CPRT","ABNB","ODFL","CTSH","EA","GEHC","ON",
    "LULU","DDOG","BKR","GFS","XEL","KHC","FANG","AEP","TEAM","ZS",
    "DLTR","SIRI","MDB","WBD","ILMN","ENPH","DASH","RIVN","LCID","PDD",
    "PYPL","NXPI","SPLK","OKTA","ARM","PLTR","SNOW","COIN","APP","SMCI",
]

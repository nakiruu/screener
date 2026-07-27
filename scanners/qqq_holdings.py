"""
scanners/qqq_holdings.py
Fetches ETF constituents for scanning universes (QQQ, SPY, or both).

Strategy per universe (tries in order):
  1. yfinance ETF holdings via ticker info
  2. Wikipedia constituents page (most reliable fallback)
  3. Hardcoded snapshot (last resort, may be stale)

Results are cached to data/{universe}_holdings_cache.json (TTL: 24 hrs).
"""

import json
import time
from pathlib import Path

CACHE_DIR  = Path("data")
CACHE_TTL  = 86_400   # 24 hours


def get_holdings(universe: str = "qqq", refresh: bool = False) -> list[str]:
    """
    Returns a deduplicated, sorted list of ticker strings for the given universe.

    universe: 'qqq', 'spy', or 'all' (union of both)
    """
    universe = universe.lower()

    if universe == "all":
        qqq = get_qqq_holdings(refresh=refresh)
        spy = get_spy_holdings(refresh=refresh)
        combined = sorted(set(qqq + spy))
        print(f"     [combined] {len(combined)} unique tickers "
              f"(QQQ: {len(qqq)}, SPY: {len(spy)})")
        return combined
    elif universe == "spy":
        return get_spy_holdings(refresh=refresh)
    else:
        return get_qqq_holdings(refresh=refresh)


def get_qqq_holdings(refresh: bool = False) -> list[str]:
    """
    Returns a list of ticker strings for all Nasdaq-100 constituents.
    Tries multiple sources; caches results locally.
    """
    cache_path = CACHE_DIR / "qqq_holdings_cache.json"
    CACHE_DIR.mkdir(exist_ok=True)

    if not refresh and cache_path.exists():
        try:
            data = json.loads(cache_path.read_text())
            age  = time.time() - data.get("fetched_at", 0)
            if age < CACHE_TTL:
                tickers = data["tickers"]
                print(f"     [cache] QQQ holdings: {len(tickers)} tickers "
                      f"(age {age/3600:.1f}h)")
                return tickers
        except Exception:
            pass

    tickers = None

    # Method 1: yfinance QQQ holdings
    try:
        import yfinance as yf
        qqq = yf.Ticker("QQQ")
        holdings = qqq.funds_data.top_holdings if hasattr(qqq, 'funds_data') else None
        if holdings is not None and len(holdings) > 50:
            tickers = list(holdings.index)
            print(f"     [yfinance] Fetched {len(tickers)} QQQ holdings")
    except Exception as e:
        print(f"     [yfinance] Failed ({e}), trying Wikipedia...")

    # Method 2: Wikipedia Nasdaq-100 page
    if not tickers or len(tickers) < 90:
        try:
            import requests
            from bs4 import BeautifulSoup

            url = "https://en.wikipedia.org/wiki/Nasdaq-100"
            resp = requests.get(url, timeout=15,
                                headers={"User-Agent": "Mozilla/5.0"})
            soup = BeautifulSoup(resp.text, "lxml")

            table = soup.find("table", {"id": "constituents"})
            if table is None:
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
                        tkr = cells[1].get_text(strip=True)
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

    # Method 3: Hardcoded snapshot
    if not tickers or len(tickers) < 90:
        tickers = _HARDCODED_QQQ
        print(f"     [snapshot] Using hardcoded QQQ list: {len(tickers)} tickers")

    tickers = _normalize(tickers)
    _write_cache(cache_path, tickers)
    return tickers


def get_spy_holdings(refresh: bool = False) -> list[str]:
    """
    Returns a list of ticker strings for S&P 500 constituents.
    Tries multiple sources; caches results locally.
    """
    cache_path = CACHE_DIR / "spy_holdings_cache.json"
    CACHE_DIR.mkdir(exist_ok=True)

    if not refresh and cache_path.exists():
        try:
            data = json.loads(cache_path.read_text())
            age  = time.time() - data.get("fetched_at", 0)
            if age < CACHE_TTL:
                tickers = data["tickers"]
                print(f"     [cache] SPY holdings: {len(tickers)} tickers "
                      f"(age {age/3600:.1f}h)")
                return tickers
        except Exception:
            pass

    tickers = None

    # Method 1: Wikipedia S&P 500 page (most reliable for SPY)
    try:
        import requests
        from bs4 import BeautifulSoup

        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        resp = requests.get(url, timeout=15,
                            headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(resp.text, "lxml")

        table = soup.find("table", {"id": "constituents"})
        if table:
            rows = table.find_all("tr")[1:]
            parsed = []
            for row in rows:
                cells = row.find_all(["td", "th"])
                if cells:
                    tkr = cells[0].get_text(strip=True)
                    if 1 <= len(tkr) <= 5 and tkr.replace(".", "").isupper():
                        parsed.append(tkr)

            if len(parsed) > 400:
                tickers = parsed
                print(f"     [wikipedia] Fetched {len(tickers)} S&P 500 tickers")
    except Exception as e:
        print(f"     [wikipedia] SPY failed ({e}), trying yfinance...")

    # Method 2: yfinance SPY holdings (usually only returns top ~20)
    if not tickers or len(tickers) < 400:
        try:
            import yfinance as yf
            spy = yf.Ticker("SPY")
            holdings = spy.funds_data.top_holdings if hasattr(spy, 'funds_data') else None
            if holdings is not None and len(holdings) > 400:
                tickers = list(holdings.index)
                print(f"     [yfinance] Fetched {len(tickers)} SPY holdings")
        except Exception:
            pass

    # Method 3: Hardcoded snapshot
    if not tickers or len(tickers) < 400:
        tickers = _HARDCODED_SPY
        print(f"     [snapshot] Using hardcoded SPY list: {len(tickers)} tickers")

    tickers = _normalize(tickers)
    _write_cache(cache_path, tickers)
    return tickers


def _normalize(tickers: list[str]) -> list[str]:
    """Normalize dots (BRK.B → BRK-B for yfinance) and deduplicate."""
    tickers = [t.replace(".", "-") for t in tickers]
    return sorted(set(tickers))


def _write_cache(cache_path: Path, tickers: list[str]) -> None:
    try:
        cache_path.write_text(json.dumps({
            "fetched_at": time.time(),
            "tickers":    tickers,
        }, indent=2))
    except Exception:
        pass


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

# ── Hardcoded snapshot (S&P 500, June 2025) ───────────────────
_HARDCODED_SPY = [
    "AAPL","ABBV","ABT","ACN","ADBE","ADI","ADM","ADP","ADSK","AEE",
    "AEP","AES","AFL","AIG","AIZ","AJG","AKAM","ALB","ALGN","ALK",
    "ALL","ALLE","AMAT","AMCR","AMD","AME","AMGN","AMP","AMT","AMZN",
    "ANET","ANSS","AON","AOS","APA","APD","APH","APTV","ARE","ATO",
    "ATVI","AVGO","AVY","AWK","AXP","AZO","BA","BAC","BAX","BBWI",
    "BBY","BDX","BEN","BF-B","BG","BIIB","BIO","BK","BKNG","BKR",
    "BLDR","BLK","BMY","BR","BRK-B","BRO","BSX","BWA","BX","BXP",
    "C","CAG","CAH","CARR","CAT","CB","CBOE","CBRE","CCI","CCL",
    "CDAY","CDNS","CDW","CE","CEG","CF","CFG","CHD","CHRW","CHTR",
    "CI","CINF","CL","CLX","CMA","CMCSA","CME","CMG","CMI","CMS",
    "CNC","CNP","COF","COO","COP","COST","CPAY","CPB","CPRT","CPT",
    "CRL","CRM","CSCO","CSGP","CSX","CTAS","CTLT","CTRA","CTSH","CTVA",
    "CVS","CVX","CZR","D","DAL","DAY","DD","DE","DECK","DFS",
    "DG","DGX","DHI","DHR","DIS","DLTR","DOV","DOW","DPZ","DRI",
    "DTE","DUK","DVA","DVN","DXCM","EA","EBAY","ECL","ED","EFX",
    "EIX","EL","EMN","EMR","ENPH","EOG","EPAM","EQIX","EQR","EQT",
    "ES","ESS","ETN","ETR","ETSY","EVRG","EW","EXC","EXPD","EXPE",
    "EXR","F","FANG","FAST","FBHS","FCX","FDS","FDX","FE","FFIV",
    "FI","FICO","FIS","FISV","FITB","FLT","FMC","FOX","FOXA","FRT",
    "FSLR","FTNT","FTV","GD","GDDY","GE","GEHC","GEN","GILD","GIS",
    "GL","GLW","GM","GNRC","GOOG","GOOGL","GPC","GPN","GRMN","GS",
    "GWW","HAL","HAS","HBAN","HCA","HOLX","HD","HSIC","HST","HSY",
    "HUBB","HUM","HWM","IBM","ICE","IDXX","IEX","IFF","ILMN","INCY",
    "INTC","INTU","INVH","IP","IPG","IQV","IR","IRM","ISRG","IT",
    "ITW","IVZ","J","JBHT","JCI","JKHY","JNJ","JNPR","JPM","K",
    "KDP","KEY","KEYS","KHC","KIM","KLAC","KMB","KMI","KMX","KO",
    "KR","KVUE","L","LDOS","LEN","LH","LHX","LIN","LKQ","LLY",
    "LMT","LNT","LOW","LRCX","LULU","LUV","LVS","LW","LYB","LYV",
    "MA","MAA","MAR","MAS","MCD","MCHP","MCK","MCO","MDLZ","MDT",
    "MET","META","MGM","MHK","MKC","MKTX","MLM","MMC","MMM","MNST",
    "MO","MOH","MOS","MPC","MPWR","MRK","MRNA","MRO","MS","MSCI",
    "MSFT","MSI","MTB","MTCH","MTD","MU","NCLH","NDAQ","NDSN","NEE",
    "NEM","NFLX","NI","NKE","NOC","NOW","NRG","NSC","NTAP","NTRS",
    "NUE","NVDA","NVR","NWL","NWS","NWSA","NXPI","O","ODFL","OGN",
    "OKE","OMC","ON","ORCL","ORLY","OTIS","OXY","PANW","PARA","PAYC",
    "PAYX","PCAR","PCG","PEG","PEP","PFE","PFG","PG","PGR","PH",
    "PHM","PKG","PLD","PLTR","PM","PNC","PNR","PNW","PODD","POOL",
    "PPG","PPL","PRU","PSA","PSX","PTC","PVH","PWR","PXD","PYPL",
    "QCOM","QRVO","RCL","REG","REGN","RF","RHI","RJF","RL","RMD",
    "ROK","ROL","ROP","ROST","RSG","RTX","RVTY","SBAC","SBUX","SCHW",
    "SEE","SHW","SJM","SLB","SMCI","SNA","SNPS","SO","SPG","SPGI",
    "SRE","STE","STLD","STT","STX","STZ","SWK","SWKS","SYF","SYK",
    "SYY","T","TAP","TDG","TDY","TECH","TEL","TER","TFC","TFX",
    "TGT","TJX","TMO","TMUS","TPR","TRGP","TRMB","TROW","TRV","TSCO",
    "TSLA","TSN","TT","TTWO","TXN","TXT","TYL","UAL","UBER","UDR",
    "UHS","ULTA","UNH","UNP","UPS","URI","USB","V","VFC","VICI",
    "VLO","VLTO","VMC","VRSK","VRSN","VRTX","VST","VTR","VTRS","VZ",
    "WAB","WAT","WBA","WBD","WDC","WEC","WELL","WFC","WHR","WM",
    "WMB","WMT","WRB","WRK","WST","WTW","WY","WYNN","XEL","XOM",
    "XRAY","XYL","YUM","ZBH","ZBRA","ZTS",
]

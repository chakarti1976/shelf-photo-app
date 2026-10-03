"""Free, no-subscription data sources for the valuation models.

- Finviz quote page:   ratios, margins, EPS, analyst growth, peers, sector
- Yahoo Finance chart: price, name, currency, 52w range, history, dividends
- SEC EDGAR XBRL:      historical FCF, EBITDA, cash, debt, shares (US filers)
- FRED CSV:            current AAA corporate bond yield (Graham)

Every fetcher returns what it could get and records failures in `warnings`,
so the UI can show which fields need to be filled in by hand.
"""

import csv
import io
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
# SEC asks automated clients to identify themselves with a contact address.
SEC_UA = os.environ.get("SEC_USER_AGENT", "StockValuation/1.0 stock-valuation@example.com")
TIMEOUT = 20
CACHE_TTL = 3600

_session = requests.Session()
_cache: dict = {}


def _get(url, headers=None, ttl=CACHE_TTL):
    hit = _cache.get(url)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    r = _session.get(url, headers=headers or {"User-Agent": BROWSER_UA}, timeout=TIMEOUT)
    r.raise_for_status()
    _cache[url] = (time.time(), r)
    return r


# ---------------------------------------------------------------- Finviz

_SUFFIX = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}


def parse_number(text):
    """'12.3%' -> 0.123, '8.19B' -> 8.19e9, '1,234' -> 1234.0, '-' -> None."""
    if text is None:
        return None
    t = text.strip().replace(",", "").replace("*", "")
    if not t or t in {"-", "N/A"}:
        return None
    m = re.match(r"^(-?\d+(?:\.\d+)?)\s*([KMBT%]?)", t)
    if not m:
        return None
    v = float(m.group(1))
    s = m.group(2)
    if s == "%":
        return round(v / 100, 8)
    return round(v * _SUFFIX.get(s, 1), 4)


def parse_finviz(html):
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.snapshot-table2") or soup.find(
        "table", class_=re.compile("snapshot-table")
    )
    raw = {}
    if table:
        cells = [td.get_text(" ", strip=True) for td in table.find_all("td")]
        for label, value in zip(cells[0::2], cells[1::2]):
            raw[label] = value

    name = None
    h2 = soup.select_one(".quote-header_ticker-wrapper_company") or soup.find(
        "h2", class_=re.compile("company")
    )
    if h2:
        name = h2.get_text(strip=True)

    def link(prefix):
        a = soup.find("a", href=re.compile(r"f=" + prefix + r"_"))
        return a.get_text(strip=True) if a else None

    peers = []
    for a in soup.find_all("a", href=re.compile(r"screener\.ashx\?t=")):
        if "peer" in a.get_text(strip=True).lower():
            m = re.search(r"t=([A-Za-z0-9.,\-]+)", a["href"])
            if m:
                peers = [p for p in m.group(1).split(",") if p]
            break

    return {"raw": raw, "name": name, "sector": link("sec"),
            "industry": link("ind"), "country": link("geo"), "peers": peers}


def _first(raw, *labels):
    for label in labels:
        if label in raw:
            return raw[label]
    return None


def _split(text, idx):
    """Finviz packs two values in some cells, e.g. 'EPS past 3/5Y' = '12% 8%'."""
    if not text:
        return None
    parts = text.split()
    return parts[idx] if len(parts) > idx else None


def finviz_metrics(parsed):
    raw = parsed["raw"]
    num = lambda *labels: parse_number(_first(raw, *labels))
    past5 = _first(raw, "EPS past 5Y")
    if past5 is None:
        past5 = _split(_first(raw, "EPS past 3/5Y"), 1)
    div_ttm = _first(raw, "Dividend TTM", "Dividend")
    return {
        "name": parsed["name"],
        "sector": parsed["sector"],
        "industry": parsed["industry"],
        "country": parsed["country"],
        "peers": parsed["peers"],
        "roa": num("ROA"),
        "roe": num("ROE"),
        "roi": num("ROI", "ROIC"),
        "grossMargin": num("Gross Margin"),
        "operMargin": num("Oper. Margin"),
        "profitMargin": num("Profit Margin"),
        "income": num("Income"),
        "sales": num("Sales"),
        "pfcf": num("P/FCF"),
        "pe": num("P/E"),
        "eps": num("EPS (ttm)"),
        "epsNext5Y": num("EPS next 5Y"),
        "epsPast5Y": parse_number(past5),
        "evEbitda": num("EV/EBITDA"),
        "dividend": parse_number(_split(div_ttm, 0)),
        "dividendYield": num("Dividend %") or parse_number((re.findall(r"\(([^)]+)\)", div_ttm or "") or [None])[0]),
        "payout": num("Payout"),
        "perfMonth": num("Perf Month"),
        "perfQuarter": num("Perf Quarter"),
        "perfHalfY": num("Perf Half Y"),
        "perfYear": num("Perf Year"),
        "sma20": num("SMA20"),
        "sma50": num("SMA50"),
        "sma200": num("SMA200"),
        "earningsDate": _first(raw, "Earnings"),
        "beta": num("Beta"),
        "volatility": _first(raw, "Volatility"),
        "rsi": num("RSI (14)"),
        "instOwn": num("Inst Own"),
        "sharesOut": num("Shs Outstand"),
        "marketCap": num("Market Cap"),
        "recom": num("Recom"),
        "targetPrice": num("Target Price"),
        "price": num("Price"),
        "volume": num("Volume"),
    }


def fetch_finviz(ticker):
    r = _get(f"https://finviz.com/quote.ashx?t={ticker}&p=d")
    return finviz_metrics(parse_finviz(r.text))


# ---------------------------------------------------------------- Yahoo

def fetch_yahoo(ticker):
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           "?range=5y&interval=1d&events=div")
    data = _get(url, ttl=900).json()
    return parse_yahoo(data)


def parse_yahoo(data):
    res = data["chart"]["result"][0]
    meta = res.get("meta", {})
    ts = res.get("timestamp") or []
    closes = (res.get("indicators", {}).get("quote") or [{}])[0].get("close") or []
    history = [(t, c) for t, c in zip(ts, closes) if c is not None]
    now = history[-1][0] if history else time.time()

    def price_days_ago(days):
        target = now - days * 86400
        prior = [c for t, c in history if t <= target]
        return prior[-1] if prior else None

    price = meta.get("regularMarketPrice") or (history[-1][1] if history else None)
    year = [(t, c) for t, c in history if t >= now - 365 * 86400]
    p1, p2 = price_days_ago(365), price_days_ago(730)

    divs = sorted((res.get("events", {}).get("dividends") or {}).values(), key=lambda d: d["date"])
    return {
        "name": meta.get("longName") or meta.get("shortName"),
        "currency": meta.get("currency"),
        "exchange": meta.get("fullExchangeName") or meta.get("exchangeName"),
        "price": price,
        "prevClose": history[-2][1] if len(history) > 1 else None,
        "high52": meta.get("fiftyTwoWeekHigh") or (max(c for _, c in year) if year else None),
        "low52": meta.get("fiftyTwoWeekLow") or (min(c for _, c in year) if year else None),
        "volume": meta.get("regularMarketVolume"),
        "return1y": (price / p1 - 1) if price and p1 else None,
        "return2y": (price / p2 - 1) if price and p2 else None,
        "history": [[datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d"), round(c, 4)] for t, c in year],
        "dividends": [{"date": datetime.fromtimestamp(d["date"], timezone.utc).strftime("%Y-%m-%d"),
                       "amount": d["amount"]} for d in divs],
    }


def dividend_summary(dividends):
    """Per year (last 5 incl. current), the last per-payment dividend, as the
    sheet's 'Изплащане на дивиденти' row; plus payments per year."""
    if not dividends:
        return None
    cutoff = (datetime.now(timezone.utc) - timedelta(days=372)).strftime("%Y-%m-%d")
    per_year = len([d for d in dividends if d["date"] >= cutoff]) or 4
    by_year = {}
    for d in dividends:
        by_year[d["date"][:4]] = d["amount"]
    years = sorted(by_year)[-5:]
    return {"years": years, "payments": [round(by_year[y], 4) for y in years],
            "perYear": per_year, "lastExDate": dividends[-1]["date"]}


# ---------------------------------------------------------------- SEC EDGAR

def sec_cik(ticker):
    r = _get("https://www.sec.gov/files/company_tickers.json",
             headers={"User-Agent": SEC_UA}, ttl=86400)
    t = ticker.upper().replace(".", "-")
    for row in r.json().values():
        if row["ticker"].upper() == t:
            return int(row["cik_str"])
    return None


def fetch_sec(ticker):
    cik = sec_cik(ticker)
    if cik is None:
        raise LookupError("Тикерът не е намерен в SEC EDGAR (вероятно не е американска компания)")
    r = _get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json",
             headers={"User-Agent": SEC_UA}, ttl=86400)
    return parse_sec(r.json())


def _units(facts, concepts, unit="USD"):
    for taxonomy in ("us-gaap", "ifrs-full"):
        for c in concepts:
            node = facts.get(taxonomy, {}).get(c)
            if not node:
                continue
            units = node.get("units", {})
            u = unit if unit in units else next(iter(units), None)
            if u and units.get(u):
                return units[u]
    return []


def _days(e):
    try:
        return (datetime.fromisoformat(e["end"]) - datetime.fromisoformat(e["start"])).days
    except (KeyError, ValueError):
        return None


def annual_series(facts, concepts):
    """{fiscal year end (YYYY): value} for full-year duration facts, latest filing wins."""
    out = {}
    for c in concepts:
        series = {}
        for e in _units(facts, [c]):
            d = _days(e)
            if d is None or not 350 <= d <= 380:
                continue
            if e.get("form") not in ("10-K", "10-K/A", "20-F", "20-F/A", "40-F"):
                continue
            series[e["end"]] = e["val"]
        for end, v in series.items():
            out.setdefault(end[:4], v)
        if out:
            break
    return dict(sorted(out.items()))


def ttm_value(facts, concepts):
    """TTM = last FY + current YTD - prior-year YTD, using the newest quarterly filing."""
    for c in concepts:
        entries = _units(facts, [c])
        if not entries:
            continue
        annual = [e for e in entries if (_days(e) or 0) in range(350, 381)]
        if not annual:
            continue
        fy = max(annual, key=lambda e: e["end"])
        ytd = [e for e in entries if e.get("form", "").startswith("10-Q")
               and e["end"] > fy["end"] and 80 <= (_days(e) or 0) <= 290]
        if not ytd:
            return fy["val"], fy["end"]
        cur = max(ytd, key=lambda e: (e["end"], _days(e)))
        prior_end = (datetime.fromisoformat(cur["end"]) - timedelta(days=365)).date()
        prior = [e for e in entries if abs((datetime.fromisoformat(e["end"]).date() - prior_end).days) <= 10
                 and abs((_days(e) or 0) - _days(cur)) <= 10]
        if not prior:
            return fy["val"], fy["end"]
        return fy["val"] + cur["val"] - prior[0]["val"], cur["end"]
    return None, None


def latest_instant(facts, concepts, unit="USD"):
    for c in concepts:
        entries = [e for e in _units(facts, [c], unit) if "start" not in e]
        if entries:
            e = max(entries, key=lambda e: e["end"])
            return e["val"], e["end"]
    return None, None


OCF = ["NetCashProvidedByUsedInOperatingActivities",
       "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
       "CashFlowsFromUsedInOperatingActivities"]
CAPEX = ["PaymentsToAcquirePropertyPlantAndEquipment",
         "PaymentsToAcquireProductiveAssets",
         "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"]
OPINC = ["OperatingIncomeLoss", "ProfitLossFromOperatingActivities"]
DA = ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization",
      "DepreciationAmortizationAndAccretionNet", "Depreciation",
      "DepreciationAndAmortisationExpense"]
CASH = ["CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        "CashAndCashEquivalents"]
DEBT_TOTAL = ["LongTermDebt", "DebtLongtermAndShorttermCombinedAmount", "LongTermDebtAndCapitalLeaseObligations"]
DEBT_PARTS = [["LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations", "NoncurrentPortionOfNoncurrentBorrowings"],
              ["LongTermDebtCurrent", "LongTermDebtAndCapitalLeaseObligationsCurrent", "CurrentPortionOfNoncurrentBorrowings"],
              ["ShortTermBorrowings", "CommercialPaper", "CurrentBorrowings"]]
EPS = ["EarningsPerShareDiluted", "EarningsPerShareBasic",
       "DilutedEarningsLossPerShare", "BasicEarningsLossPerShare"]


def parse_sec(data):
    facts = data.get("facts", {})
    M = 1e6
    ocf, capex = annual_series(facts, OCF), annual_series(facts, CAPEX)
    fcf = {y: (ocf[y] - capex.get(y, 0)) / M for y in ocf}
    ocf_ttm, ttm_end = ttm_value(facts, OCF)
    capex_ttm, _ = ttm_value(facts, CAPEX)
    fcf_ttm = (ocf_ttm - (capex_ttm or 0)) / M if ocf_ttm is not None else None

    opinc, da = annual_series(facts, OPINC), annual_series(facts, DA)
    ebitda = {y: (opinc[y] + da.get(y, 0)) / M for y in opinc}

    cash, cash_date = latest_instant(facts, CASH)
    debt, debt_date = latest_instant(facts, DEBT_TOTAL)
    if debt is None:
        parts = [latest_instant(facts, p)[0] for p in DEBT_PARTS]
        debt = sum(p for p in parts if p) if any(parts) else None
    shares, _ = latest_instant({"us-gaap": facts.get("dei", {})}, ["EntityCommonStockSharesOutstanding"], "shares")

    eps_hist = {}
    for c in EPS:
        eps_hist = annual_series_unit(facts, c)
        if eps_hist:
            break

    last = lambda d, n: dict(list(d.items())[-n:])
    return {
        "entityName": data.get("entityName"),
        "fcf": last(fcf, 10),
        "fcfTTM": fcf_ttm,
        "fcfTTMEnd": ttm_end,
        "ebitda": last(ebitda, 5),
        "cash": cash / M if cash is not None else None,
        "debt": debt / M if debt is not None else 0.0,
        "balanceDate": cash_date or debt_date,
        "sharesM": shares / M if shares else None,
        "epsHistory": last(eps_hist, 11),
    }


def annual_series_unit(facts, concept):
    """Like annual_series but for per-share units (USD/shares)."""
    for taxonomy in ("us-gaap", "ifrs-full"):
        units = facts.get(taxonomy, {}).get(concept, {}).get("units", {})
        for u, entries in units.items():
            if "/shares" not in u:
                continue
            out = {}
            for e in entries:
                d = _days(e)
                if d and 350 <= d <= 380 and e.get("form") in ("10-K", "10-K/A", "20-F", "40-F"):
                    out[e["end"][:4]] = e["val"]
            if out:
                return dict(sorted(out.items()))
    return {}


# ---------------------------------------------------------------- FRED

def fetch_aaa_yield():
    r = _get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=BAMLC0A1CAAAEY", ttl=21600)
    return parse_fred_csv(r.text)


def parse_fred_csv(text):
    rows = list(csv.reader(io.StringIO(text)))
    for row in reversed(rows[1:]):
        if len(row) >= 2 and row[1] not in ("", "."):
            return {"value": float(row[1]), "date": row[0]}
    return None


# ---------------------------------------------------------------- Peers

def fetch_yahoo_peers(ticker):
    r = _get(f"https://query2.finance.yahoo.com/v6/finance/recommendationsbysymbol/{ticker}")
    res = r.json()["finance"]["result"][0]["recommendedSymbols"]
    return [x["symbol"] for x in res]


def peer_quote(ticker):
    """Price, EPS and EV/EBITDA for a comparable company."""
    try:
        f = fetch_finviz(ticker)
        return {"ticker": ticker.upper(), "name": f["name"], "price": f["price"],
                "eps": f["eps"], "evEbitda": f["evEbitda"]}
    except Exception as e:  # noqa: BLE001 — any failure just leaves the row blank
        return {"ticker": ticker.upper(), "name": None, "price": None, "eps": None,
                "evEbitda": None, "error": str(e)}


# ---------------------------------------------------------------- All

def gather(ticker, peers=None):
    ticker = ticker.strip().upper()
    warnings = []
    jobs = {"finviz": lambda: fetch_finviz(ticker), "yahoo": lambda: fetch_yahoo(ticker),
            "sec": lambda: fetch_sec(ticker), "aaa": fetch_aaa_yield}
    out = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {k: pool.submit(f) for k, f in jobs.items()}
        for k, fut in futures.items():
            try:
                out[k] = fut.result()
            except Exception as e:  # noqa: BLE001
                out[k] = None
                warnings.append(f"{k}: {e}")

        if not peers:
            peers = (out["finviz"] or {}).get("peers") or []
            if not peers:
                try:
                    peers = fetch_yahoo_peers(ticker)
                except Exception as e:  # noqa: BLE001
                    warnings.append(f"peers: {e}")
        peers = [p.upper() for p in peers if p.upper() != ticker][:6]
        out["peers"] = list(pool.map(peer_quote, peers))

    if out["yahoo"]:
        out["dividends"] = dividend_summary(out["yahoo"]["dividends"])
    else:
        out["dividends"] = None
    out["ticker"] = ticker
    out["warnings"] = warnings
    out["fetchedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return out

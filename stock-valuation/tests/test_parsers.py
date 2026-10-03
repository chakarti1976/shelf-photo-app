"""Parser tests on small fixtures shaped like the real responses.
Run: python -m pytest tests/  (or python tests/test_parsers.py)"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import data_sources as ds  # noqa: E402

FINVIZ = """
<h2 class="quote-header_ticker-wrapper_company"><a href="#">Zeta Global Holdings Corp</a></h2>
<div class="quote-links">
 <a href="screener.ashx?v=111&f=sec_technology" class="tab-link">Technology</a>
 <a href="screener.ashx?v=111&f=ind_softwareinfrastructure" class="tab-link">Software - Infrastructure</a>
 <a href="screener.ashx?v=111&f=geo_usa" class="tab-link">USA</a>
 <a href="screener.ashx?t=PATH,DOCN,BOX&v=111" class="tab-link">Peers</a>
</div>
<table class="js-snapshot-table snapshot-table2 screener_snapshot-table-body">
<tr><td class="snapshot-td2">P/E</td><td class="snapshot-td2"><b>-</b></td>
    <td class="snapshot-td2">EPS (ttm)</td><td class="snapshot-td2"><b>-0.01</b></td>
    <td class="snapshot-td2">ROA</td><td class="snapshot-td2"><b>-0.12%</b></td></tr>
<tr><td class="snapshot-td2">EPS next 5Y</td><td class="snapshot-td2"><b>40.90%</b></td>
    <td class="snapshot-td2">EPS past 3/5Y</td><td class="snapshot-td2"><b>12.10% 8.50%</b></td>
    <td class="snapshot-td2">ROIC</td><td class="snapshot-td2"><b>-1.20%</b></td></tr>
<tr><td class="snapshot-td2">Dividend TTM</td><td class="snapshot-td2"><b>1.04 (0.45%)</b></td>
    <td class="snapshot-td2">Market Cap</td><td class="snapshot-td2"><b>8.19B</b></td>
    <td class="snapshot-td2">Shs Outstand</td><td class="snapshot-td2"><b>227.38M</b></td></tr>
<tr><td class="snapshot-td2">Price</td><td class="snapshot-td2"><b>32.63</b></td>
    <td class="snapshot-td2">EV/EBITDA</td><td class="snapshot-td2"><b>45.10</b></td>
    <td class="snapshot-td2">Volume</td><td class="snapshot-td2"><b>5,950,331</b></td></tr>
</table>"""


def test_parse_number():
    assert ds.parse_number("12.5%") == 0.125
    assert ds.parse_number("8.19B") == 8.19e9
    assert ds.parse_number("1,234") == 1234
    assert ds.parse_number("-") is None
    assert ds.parse_number("-0.01") == -0.01


def test_finviz():
    m = ds.finviz_metrics(ds.parse_finviz(FINVIZ))
    assert m["name"] == "Zeta Global Holdings Corp"
    assert m["sector"] == "Technology" and m["industry"] == "Software - Infrastructure"
    assert m["peers"] == ["PATH", "DOCN", "BOX"]
    assert m["pe"] is None and m["eps"] == -0.01
    assert abs(m["epsNext5Y"] - 0.409) < 1e-12 and abs(m["epsPast5Y"] - 0.085) < 1e-12
    assert m["roi"] == -0.012
    assert m["dividend"] == 1.04 and abs(m["dividendYield"] - 0.0045) < 1e-12
    assert m["sharesOut"] == 227.38e6 and m["evEbitda"] == 45.1 and m["volume"] == 5950331


def test_yahoo_and_dividends():
    day = 86400
    t0 = 1_700_000_000
    ts = [t0 + i * day for i in range(800)]
    closes = [10 + i * 0.01 for i in range(800)]
    divs = {str(t0 + i * 90 * day): {"amount": 0.2 + 0.01 * i, "date": t0 + i * 90 * day} for i in range(9)}
    data = {"chart": {"result": [{"meta": {"currency": "USD", "longName": "Acme", "regularMarketPrice": 18.0},
                                   "timestamp": ts, "indicators": {"quote": [{"close": closes}]},
                                   "events": {"dividends": divs}}]}}
    y = ds.parse_yahoo(data)
    assert y["name"] == "Acme" and y["price"] == 18.0
    assert abs(y["return1y"] - (18.0 / closes[799 - 365] - 1)) < 1e-9
    assert len(y["history"]) == 366 and y["high52"] == closes[-1]
    s = ds.dividend_summary(y["dividends"])
    assert s["payments"][-1] == 0.28 and len(s["years"]) <= 5


def _fact(start, end, val, form="10-K"):
    return {"start": start, "end": end, "val": val, "form": form}


def test_sec():
    usd = lambda *e: {"units": {"USD": list(e)}}
    data = {"entityName": "Acme", "facts": {
        "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [{"end": "2025-04-30", "val": 227_375_000}]}}},
        "us-gaap": {
            "NetCashProvidedByUsedInOperatingActivities": usd(
                _fact("2023-01-01", "2023-12-31", 900e6), _fact("2024-01-01", "2024-12-31", 1000e6),
                _fact("2024-01-01", "2024-06-30", 400e6, "10-Q"), _fact("2025-01-01", "2025-06-30", 500e6, "10-Q")),
            "PaymentsToAcquirePropertyPlantAndEquipment": usd(
                _fact("2023-01-01", "2023-12-31", 100e6), _fact("2024-01-01", "2024-12-31", 100e6)),
            "OperatingIncomeLoss": usd(_fact("2024-01-01", "2024-12-31", 300e6)),
            "DepreciationDepletionAndAmortization": usd(_fact("2024-01-01", "2024-12-31", 50e6)),
            "CashAndCashEquivalentsAtCarryingValue": usd({"end": "2025-06-30", "val": 757e6, "form": "10-Q"}),
            "LongTermDebt": usd({"end": "2025-06-30", "val": 1265e6, "form": "10-Q"}),
        }}}
    s = ds.parse_sec(data)
    assert s["fcf"] == {"2023": 800.0, "2024": 900.0}
    assert s["fcfTTM"] == 1000 + 500 - 400 - 100  # capex has no 10-Q → falls back to FY
    assert s["ebitda"] == {"2024": 350.0}
    assert s["cash"] == 757 and s["debt"] == 1265 and s["sharesM"] == 227.375


def test_fred():
    assert ds.parse_fred_csv("observation_date,BAMLC0A1CAAAEY\n2025-09-25,4.90\n2025-09-26,.\n") == {
        "value": 4.9, "date": "2025-09-25"}


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)

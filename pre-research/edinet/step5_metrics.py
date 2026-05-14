"""
Step 5: Compute financial / valuation metrics from time-series data.

== What this script verifies ==
Whether per-fiscal-year metrics (ROE, equity ratio, D/E, growth rates,
margins) and valuation metrics (PER, PBR) can be derived from:
  - Step 4 output: data/timeseries_{sec_code}.csv (EDINET financials)
  - yfinance: end-of-fiscal-year stock price for that ticker

== Metrics computed ==
  From EDINET alone (financial metrics):
    OperatingMargin   = OperatingIncome / NetSales
    NetMargin         = ProfitLoss      / NetSales
    ROE               = ProfitLoss      / NetAssets
    EquityRatio       = NetAssets       / TotalAssets
    DERatio           = InterestBearingDebt / NetAssets
    SalesGrowth       = NetSales / NetSales(prev) - 1
    ProfitGrowth      = ProfitLoss / ProfitLoss(prev) - 1
    BPS               = NetAssets / SharesOutstanding

  From EDINET + yfinance (valuation metrics):
    StockPrice (fiscal year-end)
    PER               = StockPrice / EPS
    PBR               = StockPrice / BPS

== yfinance ticker convention ==
For TSE-listed stocks, append ".T" to the 4-digit securities code.
Toyota 7203 -> 7203.T, Sony 6758 -> 6758.T.

== Stock-price selection rule ==
For each fiscal year-end (period_end), fetch the closing price on the
nearest trading day at or before period_end. This is the standard
convention for fiscal-year-end PER/PBR (sometimes called "期末PER").

If yfinance fails (network down, ticker not found), price-dependent
metrics are emitted as NaN and the financial metrics still complete.

== Pass criterion ==
For each fiscal year, all metrics above are computed (or marked NaN with
a clear reason). Result CSV at data/metrics_{sec_code}.csv.

Usage:
  python step5_metrics.py --sec-code 7203
"""

import argparse
from pathlib import Path

import pandas as pd
import yfinance as yf

DATA_DIR = Path(__file__).parent / "data"


def load_timeseries(sec_code: str) -> pd.DataFrame:
    csv_path = DATA_DIR / f"timeseries_{sec_code}.csv"
    if not csv_path.exists():
        raise FileNotFoundError(
            f"{csv_path} not found. Run step4_timeseries.py --sec-code {sec_code} first."
        )
    df = pd.read_csv(csv_path)
    df["period_end"] = pd.to_datetime(df["period_end"])
    return df.set_index("period_end").sort_index()


def fetch_fiscal_year_end_prices(sec_code: str, period_ends: pd.DatetimeIndex) -> pd.Series:
    """For each fiscal year-end, return the closing price on the nearest
    trading day at or before that date.

    auto_adjust=False makes the "Close" column be the value Yahoo Finance
    itself stores (split-adjusted to the latest ratio but without yfinance's
    additional dividend adjustment).

    KNOWN LIMITATION — stock-split adjustment mismatch (verified, documented
    in detail in verification_results.md):

    Both EDINET-side EPS and yfinance-side stock prices ARE split-adjusted,
    but to *different reference points*:
      - yfinance:  adjusted to the LATEST split ratio at retrieval time.
      - EDINET:    adjusted to the FILING-TIME share count, frozen into the
                   XBRL when each report was filed. So FY2022's report (filed
                   pre-split) has pre-split EPS, while a later report
                   (filed post-split) restates FY2022 EPS using the post-split
                   share count.

    Consequence: when a split happens between the period end and TODAY,
    yfinance's close for that period is already split-adjusted, but step4's
    EPS (read from the original FY's report) is not. PER ends up off by the
    split ratio.

    Production fix is to either (a) always read EPS from the latest-filed
    report (which restates older years), or (b) divide historical EPS by the
    cumulative split ratio observed in yfinance.Ticker.splits.

    Sony 6758 demonstrates this clearly:
      - FY2022 EPS in the FY2022 report:  758.38  (pre-split)
      - FY2022 EPS in the FY2024 report:  157.66  (post-split, restated)
      - yfinance Close 2023-03-31:        2,397   (post-split-equivalent)
      - Wrong PER (current behaviour): 2397/758.38 = 3.16
      - Right PER (using restated EPS): 2397/157.66 = 15.2

    Toyota 7203 happens to look fine because its 1:5 split was in 2021-09,
    before the FY2022 report was filed (2023-06). Every year in our window
    already has the post-split share count.

    yfinance returns NaN for non-trading days; we therefore pull a window
    starting ~10 days before period_end and pick the last available close.
    """
    ticker = f"{sec_code}.T"
    # Pad the start by ~10 calendar days so even long holiday weekends are
    # covered when period_end happens to fall on a closed day.
    start = (period_ends.min() - pd.Timedelta(days=10)).strftime("%Y-%m-%d")
    end = (period_ends.max() + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    print(f"yfinance: ticker={ticker}, range={start}~{end} (auto_adjust=False)")
    hist = yf.Ticker(ticker).history(start=start, end=end, auto_adjust=False)
    if hist.empty:
        raise RuntimeError(f"yfinance returned no data for {ticker}")

    # Strip tz so we can compare against tz-naive period_end values.
    hist.index = hist.index.tz_localize(None).normalize()
    closes = hist["Close"]

    prices: dict[pd.Timestamp, float] = {}
    for pe in period_ends:
        eligible = closes.loc[:pe]
        prices[pe] = float(eligible.iloc[-1]) if not eligible.empty else float("nan")
    return pd.Series(prices, name="StockPrice")


def compute_metrics(df: pd.DataFrame, prices: pd.Series) -> pd.DataFrame:
    """Combine financial figures and prices into a metrics DataFrame.

    All ratios are emitted as decimals (e.g. 0.12 means 12%). Downstream
    formatting decides whether to multiply by 100.
    """
    m = pd.DataFrame(index=df.index)

    # Financial metrics (EDINET only).
    m["OperatingMargin"] = df["OperatingIncome"] / df["NetSales"]
    m["NetMargin"] = df["ProfitLoss"] / df["NetSales"]
    m["ROE"] = df["ProfitLoss"] / df["NetAssets"]
    m["EquityRatio"] = df["NetAssets"] / df["TotalAssets"]
    m["DERatio"] = df["InterestBearingDebt"] / df["NetAssets"]

    # YoY growth — pct_change leaves the first row as NaN by design.
    m["SalesGrowth"] = df["NetSales"].pct_change()
    m["ProfitGrowth"] = df["ProfitLoss"].pct_change()

    # Per-share book value (BPS = net assets / shares outstanding).
    m["BPS"] = df["NetAssets"] / df["SharesOutstanding"]

    # Valuation metrics (require stock price).
    m["StockPrice"] = prices.reindex(m.index)
    m["PER"] = m["StockPrice"] / df["EarningsPerShare"]
    m["PBR"] = m["StockPrice"] / m["BPS"]

    return m


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sec-code", required=True, help="4-digit securities code (e.g. 7203)")
    args = parser.parse_args()

    df = load_timeseries(args.sec_code)
    print(f"Loaded {len(df)} fiscal years from timeseries_{args.sec_code}.csv")

    try:
        prices = fetch_fiscal_year_end_prices(args.sec_code, df.index)
    except Exception as e:
        # Don't kill the whole run; emit warning and produce financial-only metrics.
        print(f"[warn] yfinance failed: {e!r}. Valuation metrics will be NaN.")
        prices = pd.Series(index=df.index, dtype=float, name="StockPrice")

    metrics = compute_metrics(df, prices)

    print("\n=== Metrics ===")
    with pd.option_context(
        "display.float_format", lambda v: f"{v:,.4f}",
        "display.max_columns", None,
        "display.width", 200,
    ):
        print(metrics)

    out_path = DATA_DIR / f"metrics_{args.sec_code}.csv"
    metrics.to_csv(out_path)
    print(f"\nSaved -> {out_path}")


if __name__ == "__main__":
    main()

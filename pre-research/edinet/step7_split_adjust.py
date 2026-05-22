"""
Step 7: Verify the two candidate methods to fix the stock-split mismatch in PER.

== Background ==
Step 5 found PER off by the split ratio for years that precede a split,
because EDINET's filing-time EPS and yfinance's latest-split-adjusted prices
use different reference points.  Two repair methods were proposed:

  (a) restated EPS from the latest report's SummaryOfBusinessResults
      (Prior*YearDuration contexts hold the past 5 years' EPS already
       rebased to the post-split share count)
  (b) yfinance.Ticker.splits cumulative ratio
      (multiply backwards through every split that happened after the
       fiscal-year-end to invert yfinance's forward adjustment;
       equivalently divide raw EPS by the cumulative ratio)

Step 5 implicitly validated (a) for Sony 6758 FY2022 (Prior2YearDuration in
the FY2024 report gave 162.71, matching the expected PER ~14.7).
**(b) has never been exercised** in pre-research.  This step does it.

== What this script does ==
For one securities code (default 6758 Sony):

  1. Load doc_list_{sec_code}.csv from Step 2.
  2. Take the latest annual report and pull EPS from CurrentYearDuration
     plus every available Prior{N}YearDuration in SummaryOfBusinessResults
     — that yields method (a) restated EPS per fiscal year for up to 5 years.
  3. Pull yfinance.Ticker.splits for {sec_code}.T and compute, for each
     fiscal-year-end in doc_list, the cumulative split ratio applied AFTER
     that period_end.  Use it to derive method (b) "EPS in latest-split
     basis" = raw EPS (from each year's own report) / cumulative_after.
  4. Pull yfinance closing price at each period_end (same logic as Step 5).
  5. Print and CSV-dump a side-by-side comparison:
       period_end, raw_eps, eps_a, eps_b, price, per_raw, per_a, per_b,
       splits_after, agreement_pct
  6. Emit summary lines that the pass criteria look for.

== Pass criteria (echoed in verification_plan.md Step 7) ==
  - yfinance.Ticker.splits returns >= 1 split row for 6758.T with the
    correct date (2024-10-01) and ratio (~5.0).
  - PER_a and PER_b agree within +-1% for every fiscal year both can cover.
  - Period_ends older than ~5 years before the latest report yield NaN for
    method (a) but a real value for (b).  (Limit observed.)

== Usage ==
  python step7_split_adjust.py --sec-code 6758
"""

import argparse
import csv
import json
from pathlib import Path

import pandas as pd
import yfinance as yf

# Reuse Step 3a's primitives so the extraction logic remains the single source
# of truth.  We additionally need Prior{N}YearDuration access; that is built
# locally rather than added to step3a so the production whitelist stays clean.
from step3a_lxml import (
    download_xbrl_zip,
    find_public_xbrl,
    get_fact,
    load_api_key,
    load_xbrl_tree,
    resolve_namespaces,
)

DATA_DIR = Path(__file__).parent / "data"
OUTPUT_CSV_TEMPLATE = "split_adjust_{sec_code}.csv"

# SummaryOfBusinessResults element for parent-attributable basic EPS (IFRS).
# Same name used by Sony in Step 5 verification (verification_results.md).
EPS_ELEMENT = "BasicEarningsLossPerShareIFRSSummaryOfBusinessResults"

# Contexts to probe in the latest report.  CurrentYearDuration is the latest
# fiscal year; Prior{N}YearDuration walks back, N=1..4.
SUMMARY_CONTEXTS: list[tuple[int, str]] = [
    (0, "CurrentYearDuration"),
    (1, "Prior1YearDuration"),
    (2, "Prior2YearDuration"),
    (3, "Prior3YearDuration"),
    (4, "Prior4YearDuration"),
]


def load_doc_list(sec_code: str) -> list[dict]:
    csv_path = DATA_DIR / f"doc_list_{sec_code}.csv"
    if not csv_path.exists():
        raise FileNotFoundError(
            f"{csv_path} not found. Run step2_doc_list.py --sec-code {sec_code} first."
        )
    with csv_path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_timeseries(sec_code: str) -> pd.DataFrame:
    """Step 4 output gives us per-year EPS as read from each year's own report."""
    csv_path = DATA_DIR / f"timeseries_{sec_code}.csv"
    if not csv_path.exists():
        raise FileNotFoundError(
            f"{csv_path} not found. Run step4_timeseries.py --sec-code {sec_code} first."
        )
    df = pd.read_csv(csv_path, parse_dates=["period_end"]).set_index("period_end").sort_index()
    return df


# ---------------------------------------------------------------------------
# Method (a): restated EPS from the latest report
# ---------------------------------------------------------------------------

def extract_restated_eps(latest_doc: dict, api_key: str) -> dict[pd.Timestamp, float]:
    """Pull EPS for current + prior years from the latest report.

    Returns {period_end: eps} for every Prior{N}YearDuration that has a value.
    The latest report's CurrentYearDuration is the latest period_end; each
    Prior{N} walks back exactly N fiscal years from there.
    """
    zip_path = download_xbrl_zip(api_key, latest_doc["doc_id"])
    xbrl_name = find_public_xbrl(zip_path)
    tree = load_xbrl_tree(zip_path, xbrl_name)
    nsmap = resolve_namespaces(tree, latest_doc["edinet_code"])

    latest_period_end = pd.to_datetime(latest_doc["period_end"])

    out: dict[pd.Timestamp, float] = {}
    for offset, ctx in SUMMARY_CONTEXTS:
        value, unit, _ = get_fact(tree, nsmap, "jpcrp_cor", EPS_ELEMENT, ctx)
        if value is None:
            continue
        # period_end for Prior{N} = latest - N years.  We use DateOffset(years=N)
        # so leap years stay correct (Mar 31 stays Mar 31).
        pe = latest_period_end - pd.DateOffset(years=offset)
        out[pe] = float(value)
    return out


# ---------------------------------------------------------------------------
# Method (b): cumulative split ratio from yfinance
# ---------------------------------------------------------------------------

def fetch_splits(sec_code: str) -> pd.Series:
    """Return yfinance.Ticker.splits as a Series indexed by date (tz-naive)."""
    ticker = f"{sec_code}.T"
    splits = yf.Ticker(ticker).splits
    if splits is None or splits.empty:
        return pd.Series(dtype=float)
    splits.index = splits.index.tz_localize(None).normalize()
    return splits


def cumulative_split_after(period_end: pd.Timestamp, splits: pd.Series) -> float:
    """Product of split ratios strictly AFTER period_end.

    yfinance's Close at period_end is already adjusted to today's split basis.
    To get the original (filing-time) share count basis, we multiply by the
    cumulative ratio that has been applied since period_end.  Equivalently to
    rebase raw EPS to today's basis we divide by this number.
    """
    if splits.empty:
        return 1.0
    after = splits[splits.index > period_end]
    if after.empty:
        return 1.0
    return float(after.prod())


# ---------------------------------------------------------------------------
# Price (re-implemented inline to keep step7 self-contained and to avoid
# pulling in step5's CSV-dumping side-effects).
# ---------------------------------------------------------------------------

def fetch_closes(sec_code: str, period_ends: pd.DatetimeIndex) -> pd.Series:
    """Close at nearest trading day <= period_end.  See step5 for the rationale."""
    ticker = f"{sec_code}.T"
    start = (period_ends.min() - pd.Timedelta(days=15)).strftime("%Y-%m-%d")
    end = (period_ends.max() + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    hist = yf.Ticker(ticker).history(start=start, end=end, auto_adjust=False)
    if hist.empty:
        raise RuntimeError(f"yfinance returned no data for {ticker}")
    hist.index = hist.index.tz_localize(None).normalize()
    closes = hist["Close"]
    out: dict[pd.Timestamp, float] = {}
    for pe in period_ends:
        eligible = closes.loc[:pe]
        out[pe] = float(eligible.iloc[-1]) if not eligible.empty else float("nan")
    return pd.Series(out, name="Close")


# ---------------------------------------------------------------------------
# Pull it together
# ---------------------------------------------------------------------------

def run(sec_code: str) -> pd.DataFrame:
    api_key = load_api_key()
    docs = load_doc_list(sec_code)
    if not docs:
        raise ValueError(f"doc_list_{sec_code}.csv has no rows.")
    # Latest report = last row by period_end (doc_list is already sorted).
    docs_sorted = sorted(docs, key=lambda r: r["period_end"])
    latest_doc = docs_sorted[-1]

    ts = load_timeseries(sec_code)
    raw_eps = ts["EarningsPerShare"]
    period_ends = ts.index

    print(f"=== Step 7: split-adjust verification for {sec_code} ===")
    print(f"Latest report : docID={latest_doc['doc_id']} period_end={latest_doc['period_end']}")

    # --- Method (a) ---
    print("\n[a] extracting restated EPS from latest report's Prior*YearDuration ...")
    restated = extract_restated_eps(latest_doc, api_key)
    for pe, v in sorted(restated.items()):
        print(f"     restated[{pe.date()}] = {v:>10,.2f}")

    # --- Method (b) ---
    print("\n[b] fetching yfinance.Ticker.splits ...")
    splits = fetch_splits(sec_code)
    if splits.empty:
        print("     (no splits returned by yfinance)")
    else:
        for d, ratio in splits.items():
            print(f"     split  {d.date()}  ratio={ratio}")

    # --- Prices ---
    print("\n[*] fetching closes at each period_end ...")
    closes = fetch_closes(sec_code, period_ends)
    for pe, p in closes.items():
        print(f"     close[{pe.date()}] = {p:>10,.2f}")

    # --- Build comparison table ---
    rows = []
    for pe in period_ends:
        raw = float(raw_eps.loc[pe]) if pd.notna(raw_eps.loc[pe]) else float("nan")
        eps_a = restated.get(pe, float("nan"))
        cum_after = cumulative_split_after(pe, splits)
        # Method (b): raw EPS at filing-time share count, rebased to today's
        # split basis by dividing by the cumulative split since period_end.
        eps_b = raw / cum_after if cum_after and not pd.isna(raw) else float("nan")
        price = float(closes.loc[pe]) if pd.notna(closes.loc[pe]) else float("nan")
        per_raw = price / raw if raw else float("nan")
        per_a = price / eps_a if eps_a else float("nan")
        per_b = price / eps_b if eps_b else float("nan")
        if pd.notna(per_a) and pd.notna(per_b) and per_a:
            agreement_pct = abs(per_a - per_b) / per_a * 100.0
        else:
            agreement_pct = float("nan")
        rows.append({
            "period_end": pe.date().isoformat(),
            "raw_eps": raw,
            "eps_a_restated": eps_a,
            "eps_b_split_adj": eps_b,
            "price": price,
            "per_raw": per_raw,
            "per_a": per_a,
            "per_b": per_b,
            "cum_split_after": cum_after,
            "abs_diff_per_pct": agreement_pct,
        })
    df = pd.DataFrame(rows)

    print("\n=== Comparison (PER per year, (a) vs (b)) ===")
    with pd.option_context("display.float_format", lambda v: f"{v:,.4f}",
                           "display.max_columns", None, "display.width", 200):
        print(df.to_string(index=False))

    # --- Summary ---
    print("\n=== Summary ===")
    splits_ok = (not splits.empty)
    print(f"  yfinance returned {len(splits)} split row(s) for {sec_code}.T: "
          f"{'PASS' if splits_ok else 'FAIL (no splits)'}")

    both_present = df.dropna(subset=["per_a", "per_b"])
    if not both_present.empty:
        max_diff = both_present["abs_diff_per_pct"].max()
        within_1pct = (both_present["abs_diff_per_pct"] <= 1.0).all()
        print(f"  Years where (a) and (b) both apply: {len(both_present)}")
        print(f"  Max |per_a - per_b| / per_a: {max_diff:.4f}%  "
              f"({'PASS' if within_1pct else 'FAIL'} threshold ±1%)")
    else:
        print("  No fiscal years where both (a) and (b) yielded a value.")

    only_a = df[df["eps_a_restated"].notna() & df["eps_b_split_adj"].isna()]
    only_b = df[df["eps_a_restated"].isna() & df["eps_b_split_adj"].notna()]
    print(f"  Years covered by (a) only: {len(only_a)}")
    print(f"  Years covered by (b) only: {len(only_b)}")

    out_path = DATA_DIR / OUTPUT_CSV_TEMPLATE.format(sec_code=sec_code)
    df.to_csv(out_path, index=False)
    print(f"\nSaved -> {out_path}")
    return df


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sec-code", default="6758",
                        help="4-digit securities code (default: 6758 Sony)")
    args = parser.parse_args()
    run(args.sec_code)


if __name__ == "__main__":
    main()

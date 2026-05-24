"""
Step 2: Retrieve annual securities report (有価証券報告書) filings for a given company.

== What this script verifies ==
Whether the past N fiscal years of annual reports for a given securities code
can be enumerated via EDINET API v2, given the API's hard parameter constraints.

== EDINET API constraint (confirmed in official spec ESE140206, section 3-1-1) ==
The document-list API accepts only three parameters: date, type, Subscription-Key.
There is NO filter parameter for EDINET code, docTypeCode, or date range.
Client-side filtering on the response is the only option — so retrieving a
specific company's history requires iterating over dates and filtering locally.

== Scan strategy: target the legally-required submission window ==
By 金融商品取引法 第24条, annual reports must be filed within 3 months after the
fiscal year-end. In practice nearly all filings cluster in the 3rd month
(e.g. March fiscal-end → late June). We therefore scan only:

    [first day of (fiscal_end_month + 3) - BUFFER_DAYS,
     last  day of (fiscal_end_month + 3) + BUFFER_DAYS]

This cuts API calls from ~2,500 (10 yrs × 250 weekdays) to ~300 for 10 years.

== API spec reference ==
  Section 3-1-1, references/edinet/ESE140206.pdf
  Endpoint: GET https://disclosure.edinet-fsa.go.jp/api/v2/documents.json
  Parameters:
    date             : YYYY-MM-DD (required) — the filing date to query
    type             : 1=metadata only, 2=full list (optional, default=1)
    Subscription-Key : API key (required)
  Note: the API host is `disclosure.edinet-fsa.go.jp` (requires key), distinct
  from `disclosure2dl.edinet-fsa.go.jp` (static bulk downloads, no key).

== docTypeCode reference (references/edinet/ESE140327.xlsx) ==
  "120" : 有価証券報告書 (annual securities report)        <- target here
  "130" : 訂正有価証券報告書 (amended annual report)
  "140" : 四半期報告書   (quarterly report)
  "160" : 半期報告書     (semi-annual report)

== Pass criterion ==
Past N annual reports for the target company are listed with docID and xbrl_flag,
and written to data/doc_list_{sec_code}.csv (per-company file to support
multiple companies without overwriting prior results).

Usage:
  python step2_doc_list.py --sec-code 7203 [--years 10]

Prerequisite:
  Run step1_company_map.py first to populate data/company_map.csv.
"""

import argparse
import csv
import json
import time
from datetime import date, timedelta
from pathlib import Path

import requests

BASE_URL = "https://disclosure.edinet-fsa.go.jp/api/v2/documents.json"
COMPANY_MAP_CSV = Path(__file__).parent / "data" / "company_map.csv"
# Per-company doc list: file name embeds the 4-digit securities code so
# running step2 for multiple companies does not overwrite prior results.
OUTPUT_CSV_TEMPLATE = "doc_list_{sec_code}.csv"
# secret.json lives at the repository root (3 levels above this file:
# repo/pre-research/edinet/step2_doc_list.py -> repo/secret.json).
# It is gitignored and shared by all pre-research scripts.
CONFIG_PATH = Path(__file__).parent.parent.parent / "secret.json"

DOC_TYPE_ANNUAL = "120"

# Submission window definition.
# Target the calendar month that is MONTHS_AFTER_FISCAL_END months after the
# fiscal year-end (e.g. March fiscal-end -> June). This is where the bulk of
# filings cluster because the legal deadline is exactly 3 months out.
# BUFFER_DAYS extends the window on both sides to catch early/late filers
# without ballooning the API call count.
MONTHS_AFTER_FISCAL_END = 3
BUFFER_DAYS = 7

# Politeness interval between API calls.
# The official spec (ESE140206) does not state a rate limit, but community
# reports recommend 3-5 seconds to avoid disconnection on bulk scans.
# 1 second has been observed to work for the small windows used here; raise
# this if you see 429 or connection resets on larger scans.
SLEEP_SECONDS = 1.0

FIELDNAMES = ["edinet_code", "filer_name", "doc_id", "doc_type_code",
              "period_start", "period_end", "submit_date", "xbrl_flag"]


def load_api_key() -> str:
    with CONFIG_PATH.open() as f:
        return json.load(f)["edinet"]["api_key"]


def load_company(sec_code: str) -> dict:
    """Load company info from company_map.csv by 4-digit sec_code."""
    # EDINET stores sec_code as 5-digit with trailing zero; see step1 for details.
    padded = (sec_code + "0") if (len(sec_code) == 4 and sec_code.isdigit()) else sec_code
    with COMPANY_MAP_CSV.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["sec_code"] == padded:
                return row
    raise ValueError(f"sec_code {sec_code!r} not found. Run step1_company_map.py first.")


def fiscal_end_month(company: dict) -> int:
    """Parse fiscal_month field (e.g. '3月31日') and return the month number."""
    # fiscal_month is stored as "M月DD日" (e.g. "3月31日", "12月31日")
    raw = company.get("fiscal_month", "3月31日")
    return int(raw.split("月")[0])


def _window_for_fiscal_year(fiscal_end_m: int, fiscal_year: int) -> tuple[date, date]:
    """Return (start, end) of the submission scan window for a given fiscal year.

    Window center is the calendar month MONTHS_AFTER_FISCAL_END months after
    the fiscal year-end. Year wraps when (fiscal_end_m + 3) overflows 12
    (e.g. December fiscal-end -> March of the following calendar year).
    """
    m = fiscal_end_m + MONTHS_AFTER_FISCAL_END
    y = fiscal_year
    if m > 12:
        m -= 12
        y += 1
    start = date(y, m, 1) - timedelta(days=BUFFER_DAYS)
    if m == 12:
        end = date(y + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(y, m + 1, 1) - timedelta(days=1)
    end += timedelta(days=BUFFER_DAYS)
    return start, end


def build_scan_dates(fiscal_end_m: int, years: int) -> list[date]:
    """Enumerate weekdays to scan for the most recent `years` annual reports.

    Anchor: the latest fiscal year whose submission window has *already ended*
    on or before today. We then walk that anchor back `years` times.

    Why anchor on a closed window instead of today.year: if today is before
    the current fiscal year's window even starts (e.g. today=May, window=June),
    that window contains no filings yet. Including it would silently push the
    oldest year off the requested range — a subtle off-by-one we hit in dev.
    """
    today = date.today()

    latest_fiscal_year = today.year
    while _window_for_fiscal_year(fiscal_end_m, latest_fiscal_year)[1] > today:
        latest_fiscal_year -= 1

    scan_dates: list[date] = []
    for year_offset in range(years):
        start, end = _window_for_fiscal_year(fiscal_end_m, latest_fiscal_year - year_offset)
        d = start
        while d <= end:
            # weekday() < 5 skips Sat/Sun; EDINET returns 404 on non-business days.
            if d.weekday() < 5 and d <= today:
                scan_dates.append(d)
            d += timedelta(days=1)

    return sorted(set(scan_dates))


def fetch_docs(api_key: str, target_date: str) -> list[dict]:
    """Fetch full document list (type=2) for a given date.

    type=2 returns the full record per document (filerName, docTypeCode, period,
    xbrlFlag, etc.). type=1 returns metadata-only and cannot be filtered by
    docTypeCode, so we always use 2.
    """
    resp = requests.get(
        BASE_URL,
        params={"date": target_date, "type": 2, "Subscription-Key": api_key},
        timeout=30,
    )
    # EDINET returns 404 for dates with no disclosures (typically weekends and
    # holidays). Treat as "no documents" rather than an error.
    if resp.status_code == 404:
        return []
    resp.raise_for_status()
    return resp.json().get("results", [])


def scan(api_key: str, edinet_code: str, scan_dates: list[date]) -> list[dict]:
    hits: list[dict] = []
    print(f"Scanning {len(scan_dates)} dates (submission window only)...")
    for i, d in enumerate(scan_dates):
        results = fetch_docs(api_key, d.isoformat())
        for r in results:
            if r.get("edinetCode") == edinet_code and r.get("docTypeCode") == DOC_TYPE_ANNUAL:
                hits.append({
                    "edinet_code": r["edinetCode"],
                    "filer_name": r.get("filerName", ""),
                    "doc_id": r["docID"],
                    "doc_type_code": r.get("docTypeCode", ""),
                    "period_start": r.get("periodStart", ""),
                    "period_end": r.get("periodEnd", ""),
                    "submit_date": r.get("submitDateTime", "")[:10],
                    "xbrl_flag": r.get("xbrlFlag", ""),
                })
        if (i + 1) % 20 == 0:
            print(f"  [{i+1}/{len(scan_dates)}] found so far: {len(hits)}")
        time.sleep(SLEEP_SECONDS)

    print(f"Done. API calls: {len(scan_dates)}, filings found: {len(hits)}")
    return hits


def save_csv(rows: list[dict], sec_code: str) -> None:
    out_path = Path(__file__).parent / "data" / OUTPUT_CSV_TEMPLATE.format(sec_code=sec_code)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows_sorted = sorted(rows, key=lambda r: r["period_end"])
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows_sorted)
    print(f"Saved {len(rows_sorted)} rows -> {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sec-code", required=True, help="4-digit securities code (e.g. 7203)")
    parser.add_argument("--years", type=int, default=10, help="fiscal years to look back (default: 10)")
    args = parser.parse_args()

    api_key = load_api_key()
    company = load_company(args.sec_code)
    edinet_code = company["edinet_code"]
    print(f"Target : {company['filer_name']} (secCode={args.sec_code}, edinetCode={edinet_code})")

    fiscal_m = fiscal_end_month(company)
    print(f"Fiscal year-end month: {fiscal_m}")

    scan_dates = build_scan_dates(fiscal_m, args.years)
    print(f"Scan dates: {len(scan_dates)} weekdays across submission windows")

    hits = scan(api_key, edinet_code, scan_dates)

    if not hits:
        print("No annual reports found. Try increasing --years.")
        return

    print("\nResults:")
    for row in sorted(hits, key=lambda r: r["period_end"]):
        print(f"  period={row['period_start']} ~ {row['period_end']}  "
              f"submit={row['submit_date']}  docID={row['doc_id']}  xbrl={row['xbrl_flag']}")

    save_csv(hits, args.sec_code)


if __name__ == "__main__":
    main()

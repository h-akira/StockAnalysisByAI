"""
Step 4: Build a multi-period time-series DataFrame for a single company.

== What this script verifies ==
Whether the per-fiscal-year extraction from step3a can be repeated across
all years listed in doc_list_{sec_code}.csv and concatenated into a clean
pandas DataFrame suitable for downstream analysis.

== Inputs ==
  data/doc_list_{sec_code}.csv : produced by step2_doc_list.py.
                                 Lists docIDs for each fiscal year.

== Outputs ==
  data/timeseries_{sec_code}.csv : one row per fiscal year, one column per
                                   line item. Values are numeric (no units).

== Pipeline ==
  For each row in doc_list_{sec_code}.csv:
    1. Download XBRL zip via step3a's download_xbrl_zip() (cached on disk).
    2. Parse with lxml and resolve issuer-specific namespace.
    3. Run extract_path_a() and extract_path_b().
    4. Merge to a single fact-per-item dict via merge_paths().
    5. Append to a list keyed by period_end.

  Then convert to DataFrame, sort by period_end, write CSV.

== Scope (per agreed verification plan) ==
- Single company only; multi-company comparison and fiscal-period alignment
  (e.g. 12/31 vs 3/31) are deferred to the production implementation.
- 9 line items + FreeCF, all in JPY (EPS in JPY/share).

== Stock-split caveat for time-series interpretation ==
EPS and SharesOutstanding here are read from each fiscal year's own report
("Path B" for EPS, FilingDateInstant context for shares). This means values
are baselined to the share count at THAT report's filing time. When a stock
split happens between two reports in the series, the older row reflects the
pre-split count and the newer row reflects the post-split count.
Verified with Sony 6758 (1:5 split on 2024-10-01):
  - FY2022 row: EPS=758.38, SharesOutstanding=1,261,081,781 (pre-split)
  - FY2024 row: EPS=188.71, SharesOutstanding=6,149,810,645 (post-split)
For series-level analysis (growth rates, period-end PER) the values should be
restated to a common share basis. Step 5 documents the impact on PER/PBR.

== Pass criterion ==
- DataFrame has one row per fiscal year present in doc_list, with numeric
  values for all 9 items (where source XBRL has them) and a FreeCF column.

Usage:
  python step4_timeseries.py --sec-code 7203
"""

import argparse
import csv
from pathlib import Path

import pandas as pd

# Reuse step3a's extraction primitives. Keeping these as imports (rather than
# duplicating) ensures step3a remains the single source of truth for the
# whitelist and parsing rules.
from step3a_lxml import (
    PATH_A_ITEMS,
    download_xbrl_zip,
    extract_path_a,
    extract_path_b,
    find_public_xbrl,
    load_api_key,
    load_xbrl_tree,
    merge_paths,
    resolve_namespaces,
)

DATA_DIR = Path(__file__).parent / "data"

# Column order in the output CSV. period_end is the row index, then 9 items
# in PL/BS/CF reading order, then FreeCF (computed).
ITEM_COLUMNS = [k for k, _ in PATH_A_ITEMS] + ["FreeCF"]


def load_doc_list(sec_code: str) -> list[dict]:
    csv_path = DATA_DIR / f"doc_list_{sec_code}.csv"
    if not csv_path.exists():
        raise FileNotFoundError(
            f"{csv_path} not found. Run step2_doc_list.py --sec-code {sec_code} first."
        )
    with csv_path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def extract_one_year(api_key: str, doc: dict) -> dict[str, float | None]:
    """Extract 9+1 items for a single fiscal year (one doc_list row)."""
    zip_path = download_xbrl_zip(api_key, doc["doc_id"])
    xbrl_name = find_public_xbrl(zip_path)
    tree = load_xbrl_tree(zip_path, xbrl_name)
    nsmap = resolve_namespaces(tree, doc["edinet_code"])

    path_a = extract_path_a(tree, nsmap)
    path_b = extract_path_b(tree, nsmap)
    merged = merge_paths(path_a, path_b)

    # Convert string values to numeric. JPY items become int (we keep full
    # precision; the CSV reader for downstream analysis will downcast if
    # needed). EPS is float.
    row: dict[str, float | None] = {}
    for key in ITEM_COLUMNS:
        v = merged.get(key, {}).get("value")
        if v is None:
            row[key] = None
            continue
        # Heuristic: EPS-style numbers contain '.'; everything else is integer
        # JPY values. Avoid using merged[key]["unit"] because the unit field
        # may be missing on the FreeCF (computed) entry.
        row[key] = float(v) if "." in v else int(v)
    return row


def build_dataframe(sec_code: str) -> pd.DataFrame:
    api_key = load_api_key()
    docs = load_doc_list(sec_code)
    if not docs:
        raise ValueError(f"doc_list_{sec_code}.csv has no rows.")

    rows: list[dict] = []
    for doc in docs:
        print(f"\n[{doc['period_end']}] {doc['filer_name']} docID={doc['doc_id']}")
        items = extract_one_year(api_key, doc)
        rows.append({"period_end": doc["period_end"], **items})

    df = pd.DataFrame(rows).set_index("period_end").sort_index()
    return df


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sec-code", required=True, help="4-digit securities code (e.g. 7203)")
    args = parser.parse_args()

    df = build_dataframe(args.sec_code)

    # Pretty-print to stdout. JPY items are integers (huge numbers) and EPS
    # is a small float; keep two decimals so EPS's fractional digits don't
    # disappear (the CSV always preserves full precision).
    print("\n=== Time series (JPY for monetary items, JPY/share for EPS) ===")
    with pd.option_context(
        "display.float_format", lambda v: f"{v:,.2f}",
        "display.max_columns", None,
        "display.width", 200,
    ):
        print(df)

    out_path = DATA_DIR / f"timeseries_{args.sec_code}.csv"
    df.to_csv(out_path)
    print(f"\nSaved -> {out_path}")


if __name__ == "__main__":
    main()

"""
Step 3a: Parse XBRL annual report and extract key financial line items via lxml.

== What this script verifies ==
Whether the 9 key line items of the financial statements (BS/PL/CF) for a single
fiscal year can be extracted from an EDINET XBRL document with correct values,
units, and signs, using two independent extraction paths cross-checked against
each other.

== Target items (9) ==
  BS (3): 総資産 (TotalAssets), 純資産 (NetAssets), 有利子負債 (InterestBearingDebt)
  PL (4): 売上高 (NetSales), 営業利益 (OperatingIncome),
          当期純利益 (ProfitLoss),  EPS (EarningsPerShare)
  CF (4): 営業CF (CashFlowsFromOperatingActivities),
          投資CF (CashFlowsFromInvestingActivities),
          財務CF (CashFlowsFromFinancingActivities),
          フリーCF (= 営業CF + 投資CF, computed)

== Two extraction paths ==
EDINET XBRL exposes the same numbers in multiple places. We extract from both
to cross-check; consistency between them is part of the pass criterion.

  Path A — main financial statements (連結IFRS本体):
    Uses elements in jpigp_cor / issuer-specific namespaces with
    `CurrentYearDuration` or `CurrentYearInstant` context.
    Covers PL/BS/CF directly. Required for operating income and
    interest-bearing debt (no Summary equivalent exists).

  Path B — Summary of Business Results (経営指標等の要約):
    Uses jpcrp_cor:*SummaryOfBusinessResults elements which give the latest
    five fiscal years in one place. Convenient for time-series later, but
    does not cover all items.

== EDINET XBRL structure note ==
A document zip contains XBRL/PublicDoc/ (submitted report) and XBRL/AuditDoc/
(audit report). Main financial figures live in PublicDoc, in a file named
`jpcrp030000-asr-{form-id}_{edinetCode}-000_{period}_{seq}_{submit}.xbrl`.

Namespaces:
  jppfs_cor          — Japanese GAAP (in Toyota's case: parent-only statements)
  jpigp_cor          — IFRS (consolidated statements)
  jpcrp_cor          — disclosure-form taxonomy (summary tables etc.)
  jpcrp030000-asr_{EDINETcode}-000
                     — issuer-specific extension (e.g. SalesRevenuesIFRS).
                     Each company has its own URI; resolved at runtime.

Contexts (relevant subset):
  CurrentYearDuration  — current fiscal year, flow items (PL, CF)
  CurrentYearInstant   — fiscal year-end, stock items (BS)
  Prior{N}YearDuration / Instant — N years before
  *_Member             — breakdowns by segment, person, etc. (filtered out)
  *_NonConsolidatedMember — parent-only (filtered out for consolidated reading)

== Pass criterion ==
- Path A returns non-null values for all 9 items.
- Where Path B has the same item, A and B agree (within rounding).
- Numbers/signs/units are sane and consistent with the PDF report.

Usage:
  python step3a_lxml.py --doc-id S100VWVY                # extract & compare
  python step3a_lxml.py --doc-id S100VWVY --explore      # element inventory
  python step3a_lxml.py --doc-id S100VWVY --show-contexts  # context inventory
"""

import argparse
import csv
import json
import zipfile
from pathlib import Path
from typing import Iterable

import requests
from lxml import etree

BASE_URL = "https://disclosure.edinet-fsa.go.jp/api/v2/documents"
COMPANY_MAP_CSV = Path(__file__).parent / "data" / "company_map.csv"
# doc_list files are written per-company by step2: doc_list_{sec_code}.csv.
# Search all of them when looking up by docID; require sec_code when looking
# up by year.
DOC_LIST_GLOB = "doc_list_*.csv"
DATA_DIR = Path(__file__).parent / "data"
CACHE_DIR = Path(__file__).parent / "data" / "cache" / "xbrl"
CONFIG_PATH = Path(__file__).parent.parent.parent / "secret.json"

# Issuer-specific namespace prefix template.
# Each EDINET filer has its own extension namespace whose prefix follows
# this pattern. We resolve the actual URI at runtime from root.nsmap.
ISSUER_PREFIX_TEMPLATE = "jpcrp030000-asr_{edinet_code}-000"

# Context IDs used for the current fiscal year (consolidated, no member).
CTX_DURATION = "CurrentYearDuration"   # flow items (PL, CF)
CTX_INSTANT = "CurrentYearInstant"     # stock items (BS at fiscal year-end)

# Path A whitelist: element specs for main IFRS consolidated statements.
# Each entry: (item_key, [(prefix, localname, context), ...]).
# A list of candidates is used because the issuer-specific namespace varies by
# company; we pick the first match found in the XBRL.
PATH_A_ITEMS: list[tuple[str, list[tuple[str, str, str]]]] = [
    # PL
    ("NetSales", [
        # Issuer-extension element names for "sales / total revenue" vary by
        # company and industry. Probed in order of specificity:
        #   - SalesAndFinancialServicesRevenueIFRS: companies with a financial
        #     services arm (e.g. Sony, where total revenue = goods + financial)
        #   - SalesRevenuesIFRS: standard IFRS revenue (e.g. Toyota)
        # If neither, fall back to jpigp_cor:NetSalesIFRS (which for companies
        # like Sony is "goods only" and undercounts) and finally JGAAP NetSales.
        ("ISSUER", "SalesAndFinancialServicesRevenueIFRS", CTX_DURATION),
        ("ISSUER", "SalesRevenuesIFRS", CTX_DURATION),
        ("jpigp_cor", "NetSalesIFRS", CTX_DURATION),
        ("jppfs_cor", "NetSales", CTX_DURATION),
    ]),
    ("OperatingIncome", [
        ("jpigp_cor", "OperatingProfitLossIFRS", CTX_DURATION),
        ("jppfs_cor", "OperatingIncome", CTX_DURATION),
    ]),
    ("ProfitLoss", [
        ("jpigp_cor", "ProfitLossAttributableToOwnersOfParentIFRS", CTX_DURATION),
        ("jppfs_cor", "ProfitLoss", CTX_DURATION),
    ]),
    ("EarningsPerShare", [
        # No direct EPS in jpigp_cor / jppfs_cor — fall through to Path B value.
    ]),
    # BS
    ("TotalAssets", [
        ("jpigp_cor", "LiabilitiesAndEquityIFRS", CTX_INSTANT),
        ("jppfs_cor", "Assets", CTX_INSTANT),
    ]),
    ("NetAssets", [
        # Use parent-attributable equity to match Path B and the conventional
        # "純資産" used in retail-style financial analysis. EquityIFRS (total)
        # includes non-controlling interests; the difference is meaningful but
        # not what users typically want first.
        ("jpigp_cor", "EquityAttributableToOwnersOfParentIFRS", CTX_INSTANT),
        ("jppfs_cor", "NetAssets", CTX_INSTANT),
    ]),
    ("InterestBearingDebt", [
        # Sum of current + non-current interest-bearing liabilities (IFRS).
        # Handled as a special case in extract_path_a() because it sums two
        # elements rather than reading one.
    ]),
    # CF
    ("OperatingCF", [
        # Main CF statement element name varies — Path B is more reliable here.
    ]),
    ("InvestingCF", []),
    ("FinancingCF", []),
]

# Path B whitelist: element specs from SummaryOfBusinessResults.
# All in jpcrp_cor namespace. Latest year value uses CTX_DURATION/CTX_INSTANT.
PATH_B_ITEMS: list[tuple[str, str, str]] = [
    # (item_key, localname, context)
    ("NetSales", "NetSalesSummaryOfBusinessResults", CTX_DURATION),  # parent-only
    ("OperatingIncome", "", ""),  # not in Summary
    ("ProfitLoss", "ProfitLossAttributableToOwnersOfParentIFRSSummaryOfBusinessResults", CTX_DURATION),
    ("EarningsPerShare", "BasicEarningsLossPerShareIFRSSummaryOfBusinessResults", CTX_DURATION),
    ("TotalAssets", "TotalAssetsIFRSSummaryOfBusinessResults", CTX_INSTANT),
    ("NetAssets", "EquityAttributableToOwnersOfParentIFRSSummaryOfBusinessResults", CTX_INSTANT),
    ("InterestBearingDebt", "", ""),  # not in Summary
    ("OperatingCF", "CashFlowsFromUsedInOperatingActivitiesIFRSSummaryOfBusinessResults", CTX_DURATION),
    ("InvestingCF", "CashFlowsFromUsedInInvestingActivitiesIFRSSummaryOfBusinessResults", CTX_DURATION),
    ("FinancingCF", "CashFlowsFromUsedInFinancingActivitiesIFRSSummaryOfBusinessResults", CTX_DURATION),
]


def load_api_key() -> str:
    with CONFIG_PATH.open() as f:
        return json.load(f)["edinet"]["api_key"]


def find_doc(doc_id: str | None, sec_code: str | None, year: int | None) -> dict:
    """Look up a row in doc_list_*.csv either by docID or (sec_code, year)."""
    if sec_code:
        # Look only in that company's CSV; faster and unambiguous.
        csv_path = DATA_DIR / f"doc_list_{sec_code}.csv"
        if not csv_path.exists():
            raise FileNotFoundError(
                f"{csv_path} not found. Run step2_doc_list.py --sec-code {sec_code} first."
            )
        with csv_path.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if doc_id and r["doc_id"] == doc_id:
                    return r
                if year and r["period_end"].startswith(str(year)):
                    return r
        raise ValueError(f"No matching doc in {csv_path}")
    # No sec_code -> search every doc_list_*.csv (typical when only docID known).
    csv_paths = sorted(DATA_DIR.glob(DOC_LIST_GLOB))
    if not csv_paths:
        raise FileNotFoundError(
            f"No doc_list_*.csv under {DATA_DIR}. Run step2_doc_list.py first."
        )
    for csv_path in csv_paths:
        with csv_path.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r["doc_id"] == doc_id:
                    return r
    raise ValueError(f"docID {doc_id!r} not found in any {DOC_LIST_GLOB}")


def download_xbrl_zip(api_key: str, doc_id: str) -> Path:
    """Download XBRL zip (type=1) to cache and return its path. Cached on disk.

    NOTE on document-retrieval API `type` (ESE140206 §3-2-1, different meaning
    from the document-list API's `type`):
        type=1 -> XBRL zip (submitted document + audit report)
        type=2 -> PDF
        type=3 -> alternative/attachment documents
        type=4 -> English files
        type=5 -> main-items CSV
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = CACHE_DIR / f"{doc_id}.zip"
    if zip_path.exists():
        print(f"[cache] {zip_path.name} already exists ({zip_path.stat().st_size:,} bytes)")
        return zip_path
    url = f"{BASE_URL}/{doc_id}"
    print(f"Downloading {doc_id} ...")
    resp = requests.get(
        url,
        params={"type": 1, "Subscription-Key": api_key},
        timeout=60,
    )
    resp.raise_for_status()
    zip_path.write_bytes(resp.content)
    print(f"Saved {zip_path} ({len(resp.content):,} bytes)")
    return zip_path


def find_public_xbrl(zip_path: Path) -> str:
    """Return the name of the main .xbrl inside PublicDoc/."""
    with zipfile.ZipFile(zip_path) as zf:
        candidates = [
            n for n in zf.namelist()
            if n.startswith("XBRL/PublicDoc/") and n.endswith(".xbrl")
        ]
    if not candidates:
        raise FileNotFoundError(f"No .xbrl under XBRL/PublicDoc/ in {zip_path}")
    if len(candidates) > 1:
        print(f"[warn] multiple .xbrl found, using first: {candidates}")
    return candidates[0]


def list_zip_contents(zip_path: Path) -> None:
    """Print top-level structure of the zip (for exploration)."""
    print(f"\n== Contents of {zip_path.name} ==")
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            print(f"  {info.file_size:>10,}  {info.filename}")


def load_xbrl_tree(zip_path: Path, xbrl_name: str) -> etree._ElementTree:
    with zipfile.ZipFile(zip_path) as zf:
        with zf.open(xbrl_name) as f:
            return etree.parse(f)


def explore_elements(tree: etree._ElementTree) -> None:
    """Print element-name inventory grouped by namespace prefix, with sample values.

    Goal: identify which prefixed element names map to the 9 target items.
    """
    root = tree.getroot()
    nsmap = {prefix: uri for prefix, uri in root.nsmap.items() if prefix}
    print("\n== Namespaces ==")
    for prefix, uri in sorted(nsmap.items()):
        print(f"  {prefix:20s} {uri}")

    # Group elements by (prefix, localname); count occurrences and show one sample.
    counts: dict[tuple[str, str], int] = {}
    samples: dict[tuple[str, str], str] = {}
    uri_to_prefix = {uri: prefix for prefix, uri in nsmap.items()}

    for el in root.iter():
        tag = el.tag
        if not isinstance(tag, str) or not tag.startswith("{"):
            continue
        uri, _, local = tag[1:].partition("}")
        prefix = uri_to_prefix.get(uri, "?")
        key = (prefix, local)
        counts[key] = counts.get(key, 0) + 1
        if key not in samples and el.text and el.text.strip():
            samples[key] = el.text.strip()[:60]

    print(f"\n== Element inventory ({len(counts)} distinct elements) ==")
    # Sort by prefix then localname.
    for key in sorted(counts.keys()):
        prefix, local = key
        sample = samples.get(key, "")
        print(f"  {prefix:18s} {local:60s} count={counts[key]:4d}  sample={sample!r}")


def resolve_namespaces(tree: etree._ElementTree, edinet_code: str) -> dict[str, str]:
    """Build a prefix -> URI map, resolving the ISSUER placeholder.

    EDINET extension namespaces are issuer-specific (e.g.
    `jpcrp030000-asr_E02144-000` for Toyota). We look the actual prefix up in
    the document's nsmap and expose it under the synthetic key "ISSUER" so
    that whitelist entries stay company-agnostic.
    """
    root = tree.getroot()
    nsmap = {p: u for p, u in root.nsmap.items() if p}
    issuer_prefix = ISSUER_PREFIX_TEMPLATE.format(edinet_code=edinet_code)
    if issuer_prefix in nsmap:
        nsmap["ISSUER"] = nsmap[issuer_prefix]
    return nsmap


def get_fact(
    tree: etree._ElementTree,
    nsmap: dict[str, str],
    prefix: str,
    local: str,
    context: str,
) -> tuple[str | None, str | None, str | None]:
    """Look up a single (element, context) and return (value, unit, decimals).

    Returns (None, None, None) if not found. Multiple matches on the same
    context would be an XBRL anomaly; we take the first.
    """
    uri = nsmap.get(prefix)
    if not uri:
        return None, None, None
    tag = f"{{{uri}}}{local}"
    for el in tree.getroot().iter(tag):
        if el.get("contextRef") == context:
            return (el.text or "").strip(), el.get("unitRef"), el.get("decimals")
    return None, None, None


def extract_path_a(tree: etree._ElementTree, nsmap: dict[str, str]) -> dict[str, dict]:
    """Extract 9 items from main IFRS consolidated statements (Path A)."""
    results: dict[str, dict] = {}

    for item_key, candidates in PATH_A_ITEMS:
        chosen = None
        for prefix, local, ctx in candidates:
            value, unit, dec = get_fact(tree, nsmap, prefix, local, ctx)
            if value is not None:
                chosen = {
                    "value": value, "unit": unit, "decimals": dec,
                    "source": f"{prefix}:{local}@{ctx}",
                }
                break
        results[item_key] = chosen or {"value": None, "source": "not found"}

    # Special case: InterestBearingDebt is a sum of current and non-current
    # interest-bearing liability items. Element names vary by company because
    # there is no single canonical "interest-bearing debt" element in IFRS.
    # We try two known patterns:
    #   Pattern 1 (Toyota): `InterestBearingLiabilitiesCLIFRS + NCLIFRS`
    #     in jpigp_cor — one element each for current and non-current.
    #   Pattern 2 (Sony): `BorrowingsCLIFRS + CurrentPortionOfLongTermDebtCLIFRS
    #     + LongTermDebt2NCLIFRS` — short-term borrowings, current portion of
    #     long-term, and non-current long-term as three separate elements.
    debt_summands: list[tuple[str, str, str]] = []  # (prefix, local, ctx)
    # Pattern 1
    if get_fact(tree, nsmap, "jpigp_cor", "InterestBearingLiabilitiesCLIFRS", CTX_INSTANT)[0]:
        debt_summands = [
            ("jpigp_cor", "InterestBearingLiabilitiesCLIFRS", CTX_INSTANT),
            ("jpigp_cor", "InterestBearingLiabilitiesNCLIFRS", CTX_INSTANT),
        ]
    # Pattern 2
    elif get_fact(tree, nsmap, "jpigp_cor", "BorrowingsCLIFRS", CTX_INSTANT)[0]:
        debt_summands = [
            ("jpigp_cor", "BorrowingsCLIFRS", CTX_INSTANT),
            ("ISSUER", "CurrentPortionOfLongTermDebtCLIFRS", CTX_INSTANT),
            ("ISSUER", "LongTermDebt2NCLIFRS", CTX_INSTANT),
        ]

    if debt_summands:
        parts: list[int] = []
        sources: list[str] = []
        for prefix, local, ctx in debt_summands:
            v, _, _ = get_fact(tree, nsmap, prefix, local, ctx)
            if v is not None:
                parts.append(int(v))
                sources.append(f"{prefix}:{local}")
        if parts:
            results["InterestBearingDebt"] = {
                "value": str(sum(parts)), "unit": "JPY", "decimals": "-6",
                "source": f"sum of [{', '.join(sources)}] @{CTX_INSTANT}",
            }

    return results


def extract_path_b(tree: etree._ElementTree, nsmap: dict[str, str]) -> dict[str, dict]:
    """Extract items from SummaryOfBusinessResults (Path B)."""
    results: dict[str, dict] = {}
    for item_key, local, ctx in PATH_B_ITEMS:
        if not local:
            results[item_key] = {"value": None, "source": "n/a in Summary"}
            continue
        value, unit, dec = get_fact(tree, nsmap, "jpcrp_cor", local, ctx)
        results[item_key] = {
            "value": value, "unit": unit, "decimals": dec,
            "source": f"jpcrp_cor:{local}@{ctx}",
        } if value is not None else {"value": None, "source": "not found"}
    return results


def _fmt_value(item: dict) -> str:
    v = item.get("value")
    if v is None:
        return "—"
    unit = item.get("unit") or ""
    if unit == "JPY":
        try:
            return f"{int(v):>20,} JPY"
        except ValueError:
            return f"{v} {unit}"
    if unit == "JPYPerShares":
        return f"{float(v):>20,.2f} JPY/share"
    return f"{v} {unit}"


def print_comparison(path_a: dict[str, dict], path_b: dict[str, dict]) -> None:
    items_in_order = [k for k, _ in PATH_A_ITEMS]
    print(f"\n{'item':22s} {'Path A (main IFRS)':38s}  {'Path B (Summary)':38s}")
    print("-" * 100)
    for key in items_in_order:
        a = path_a.get(key, {"value": None})
        b = path_b.get(key, {"value": None})
        print(f"{key:22s} {_fmt_value(a):38s}  {_fmt_value(b):38s}")

    # Free cash flow is computed, not extracted.
    op = path_b.get("OperatingCF", {}).get("value")
    inv = path_b.get("InvestingCF", {}).get("value")
    if op and inv:
        fcf = int(op) + int(inv)
        print(f"{'FreeCF (computed)':22s} {'(see CF rows)':38s}  {f'{fcf:>20,} JPY':38s}")

    print("\n=== Source elements ===")
    print("\nPath A:")
    for k in items_in_order:
        print(f"  {k:22s} {path_a.get(k, {}).get('source', '?')}")
    print("\nPath B:")
    for k in items_in_order:
        print(f"  {k:22s} {path_b.get(k, {}).get('source', '?')}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc-id", help="docID from doc_list.csv (e.g. S100VWVY)")
    parser.add_argument("--sec-code", help="alternative: securities code (uses latest year in doc_list.csv)")
    parser.add_argument("--year", type=int, help="fiscal year (required with --sec-code)")
    parser.add_argument("--explore", action="store_true", help="print element-name inventory instead of extracting")
    parser.add_argument("--show-contents", action="store_true", help="also list zip contents (verbose)")
    args = parser.parse_args()

    if not args.doc_id and not (args.sec_code and args.year):
        parser.error("provide --doc-id OR both --sec-code and --year")

    doc = find_doc(args.doc_id, args.sec_code, args.year)
    print(f"Target: {doc['filer_name']} (docID={doc['doc_id']}, "
          f"edinetCode={doc['edinet_code']}, period={doc['period_start']}~{doc['period_end']})")

    api_key = load_api_key()
    zip_path = download_xbrl_zip(api_key, doc["doc_id"])

    if args.show_contents:
        list_zip_contents(zip_path)

    xbrl_name = find_public_xbrl(zip_path)
    print(f"Main XBRL: {xbrl_name}")

    tree = load_xbrl_tree(zip_path, xbrl_name)

    if args.explore:
        explore_elements(tree)
        return

    nsmap = resolve_namespaces(tree, doc["edinet_code"])
    if "ISSUER" not in nsmap:
        print(f"[warn] issuer-specific namespace not found "
              f"(expected prefix {ISSUER_PREFIX_TEMPLATE.format(edinet_code=doc['edinet_code'])})")

    path_a = extract_path_a(tree, nsmap)
    path_b = extract_path_b(tree, nsmap)
    print_comparison(path_a, path_b)


if __name__ == "__main__":
    main()

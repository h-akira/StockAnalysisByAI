"""XBRL download and parse.

Direct successor of pre-research/edinet/step3a_lxml.py. The whitelist-based
extraction logic that was validated end-to-end is kept verbatim; only I/O
is adjusted so that XBRL zips live under cache/xbrl/ and the API key comes
from scripts.config.

Public surface:
    download_xbrl_zip(api_key, doc_id) -> Path
        Cached zip download (idempotent on disk).
    extract_from_zip(zip_path, edinet_code) -> ExtractResult
        Parse one zip and return a merged extraction with metadata.

Whitelist extraction (Path A + Path B) lives here. Elements that fall
outside the whitelist are returned in ExtractResult.unresolved so that
mapping_resolver (Phase P8) can hand them to an LLM for case-by-case
mapping; see plan.md §4.4.
"""

from __future__ import annotations

import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import requests
from lxml import etree

from scripts import paths

BASE_URL = "https://disclosure.edinet-fsa.go.jp/api/v2/documents"

ISSUER_PREFIX_TEMPLATE = "jpcrp030000-asr_{edinet_code}-000"
CTX_DURATION = "CurrentYearDuration"
CTX_INSTANT = "CurrentYearInstant"
CTX_FILING_DATE = "FilingDateInstant"

# Path A whitelist: (item_key, [(prefix, localname, context), ...])
# Whitelist contents are verbatim from step3a; do not edit without re-running
# the pre-research verification on Toyota and Sony.
PATH_A_ITEMS: list[tuple[str, list[tuple[str, str, str]]]] = [
    ("NetSales", [
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
    ("EarningsPerShare", []),  # falls through to Path B
    ("TotalAssets", [
        ("jpigp_cor", "LiabilitiesAndEquityIFRS", CTX_INSTANT),
        ("jppfs_cor", "Assets", CTX_INSTANT),
    ]),
    ("NetAssets", [
        ("jpigp_cor", "EquityAttributableToOwnersOfParentIFRS", CTX_INSTANT),
        ("jppfs_cor", "NetAssets", CTX_INSTANT),
    ]),
    ("InterestBearingDebt", []),  # handled by special-case sum logic below
    ("OperatingCF", []),
    ("InvestingCF", []),
    ("FinancingCF", []),
    ("SharesOutstanding", [
        ("jpcrp_cor", "NumberOfIssuedSharesAsOfFiscalYearEndIssuedSharesTotalNumberOfSharesEtc", CTX_FILING_DATE),
    ]),
]

# Path B whitelist (SummaryOfBusinessResults).
PATH_B_ITEMS: list[tuple[str, str, str]] = [
    ("NetSales", "NetSalesSummaryOfBusinessResults", CTX_DURATION),
    ("OperatingIncome", "", ""),
    ("ProfitLoss", "ProfitLossAttributableToOwnersOfParentIFRSSummaryOfBusinessResults", CTX_DURATION),
    ("EarningsPerShare", "BasicEarningsLossPerShareIFRSSummaryOfBusinessResults", CTX_DURATION),
    ("TotalAssets", "TotalAssetsIFRSSummaryOfBusinessResults", CTX_INSTANT),
    ("NetAssets", "EquityAttributableToOwnersOfParentIFRSSummaryOfBusinessResults", CTX_INSTANT),
    ("InterestBearingDebt", "", ""),
    ("OperatingCF", "CashFlowsFromUsedInOperatingActivitiesIFRSSummaryOfBusinessResults", CTX_DURATION),
    ("InvestingCF", "CashFlowsFromUsedInInvestingActivitiesIFRSSummaryOfBusinessResults", CTX_DURATION),
    ("FinancingCF", "CashFlowsFromUsedInFinancingActivitiesIFRSSummaryOfBusinessResults", CTX_DURATION),
    ("SharesOutstanding", "", ""),
]

ITEM_KEYS = [k for k, _ in PATH_A_ITEMS]


@dataclass
class ExtractResult:
    doc_id: str
    edinet_code: str
    merged: dict[str, dict] = field(default_factory=dict)
    path_a: dict[str, dict] = field(default_factory=dict)
    path_b: dict[str, dict] = field(default_factory=dict)
    unresolved: list[str] = field(default_factory=list)  # item_keys still None after merge


# ---------------------------------------------------------------------------
# Download / open
# ---------------------------------------------------------------------------

def xbrl_cache_path(doc_id: str) -> Path:
    return paths.XBRL_DIR / f"{doc_id}.zip"


def download_xbrl_zip(
    api_key: str,
    doc_id: str,
    *,
    timeout: float = 60.0,
    max_retries: int = 3,
    backoff_seconds: float = 5.0,
) -> Path:
    """Download XBRL zip (type=1) into cache/xbrl/{doc_id}.zip. Idempotent.

    Retries with exponential backoff on HTTP 429 and 5xx, and on network
    exceptions (DNS/connection/timeout). Other 4xx errors propagate.
    """
    paths.ensure_cache_dirs()
    zip_path = xbrl_cache_path(doc_id)
    if zip_path.exists():
        return zip_path
    url = f"{BASE_URL}/{doc_id}"
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            resp = requests.get(
                url,
                params={"type": 1, "Subscription-Key": api_key},
                timeout=timeout,
            )
        except requests.RequestException as e:
            last_exc = e
            if attempt + 1 < max_retries:
                time.sleep(backoff_seconds * (2 ** attempt))
                continue
            raise
        if resp.status_code == 429 or 500 <= resp.status_code < 600:
            if attempt + 1 < max_retries:
                time.sleep(backoff_seconds * (2 ** attempt))
                continue
            resp.raise_for_status()
        resp.raise_for_status()
        zip_path.write_bytes(resp.content)
        return zip_path
    raise last_exc if last_exc else RuntimeError("download_xbrl_zip: retry loop exhausted")


def find_public_xbrl(zip_path: Path) -> str:
    with zipfile.ZipFile(zip_path) as zf:
        candidates = [
            n for n in zf.namelist()
            if n.startswith("XBRL/PublicDoc/") and n.endswith(".xbrl")
        ]
    if not candidates:
        raise FileNotFoundError(f"No .xbrl under XBRL/PublicDoc/ in {zip_path}")
    return candidates[0]


def load_xbrl_tree(zip_path: Path, xbrl_name: str) -> etree._ElementTree:
    with zipfile.ZipFile(zip_path) as zf:
        with zf.open(xbrl_name) as f:
            return etree.parse(f)


def resolve_namespaces(tree: etree._ElementTree, edinet_code: str) -> dict[str, str]:
    """Build prefix -> URI map. Issuer-specific URI exposed under "ISSUER"."""
    root = tree.getroot()
    nsmap = {p: u for p, u in root.nsmap.items() if p}
    issuer_prefix = ISSUER_PREFIX_TEMPLATE.format(edinet_code=edinet_code)
    if issuer_prefix in nsmap:
        nsmap["ISSUER"] = nsmap[issuer_prefix]
    return nsmap


# ---------------------------------------------------------------------------
# Fact lookup + Path A/B extraction (verbatim from step3a)
# ---------------------------------------------------------------------------

def get_fact(
    tree: etree._ElementTree,
    nsmap: dict[str, str],
    prefix: str,
    local: str,
    context: str,
) -> tuple[str | None, str | None, str | None]:
    uri = nsmap.get(prefix)
    if not uri:
        return None, None, None
    tag = f"{{{uri}}}{local}"
    for el in tree.getroot().iter(tag):
        if el.get("contextRef") == context:
            return (el.text or "").strip(), el.get("unitRef"), el.get("decimals")
    return None, None, None


def extract_path_a(tree: etree._ElementTree, nsmap: dict[str, str]) -> dict[str, dict]:
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

    # Special case for InterestBearingDebt: sum of multiple per-issuer elements.
    # Pattern 1 (Toyota): two jpigp_cor lines.
    # Pattern 2 (Sony):   one jpigp_cor + two ISSUER lines.
    debt_summands: list[tuple[str, str, str]] = []
    if get_fact(tree, nsmap, "jpigp_cor", "InterestBearingLiabilitiesCLIFRS", CTX_INSTANT)[0]:
        debt_summands = [
            ("jpigp_cor", "InterestBearingLiabilitiesCLIFRS", CTX_INSTANT),
            ("jpigp_cor", "InterestBearingLiabilitiesNCLIFRS", CTX_INSTANT),
        ]
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
    results: dict[str, dict] = {}
    for item_key, local, ctx in PATH_B_ITEMS:
        if not local:
            results[item_key] = {"value": None, "source": "n/a in Summary"}
            continue
        value, unit, dec = get_fact(tree, nsmap, "jpcrp_cor", local, ctx)
        results[item_key] = (
            {"value": value, "unit": unit, "decimals": dec,
             "source": f"jpcrp_cor:{local}@{ctx}"}
            if value is not None
            else {"value": None, "source": "not found"}
        )
    return results


def merge_paths(path_a: dict[str, dict], path_b: dict[str, dict]) -> dict[str, dict]:
    """Pick the best value per item from Path A and Path B."""
    merged: dict[str, dict] = {}
    for key in ITEM_KEYS:
        a = path_a.get(key) or {"value": None}
        b = path_b.get(key) or {"value": None}
        if a.get("value") is not None:
            merged[key] = {**a, "path": "A"}
        elif b.get("value") is not None:
            merged[key] = {**b, "path": "B"}
        else:
            merged[key] = {"value": None, "source": "not found", "path": None}
    # FreeCF = OperatingCF + InvestingCF (computed; absent in either path).
    op = merged.get("OperatingCF", {}).get("value")
    inv = merged.get("InvestingCF", {}).get("value")
    if op is not None and inv is not None:
        merged["FreeCF"] = {
            "value": str(int(op) + int(inv)),
            "unit": "JPY", "decimals": "-6",
            "source": "OperatingCF + InvestingCF",
            "path": "computed",
        }
    else:
        merged["FreeCF"] = {"value": None, "source": "depends on CF rows", "path": None}
    return merged


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------

def extract_from_zip(zip_path: Path, edinet_code: str, doc_id: str) -> ExtractResult:
    """Parse an XBRL zip and return Path A / B / merged + unresolved items."""
    xbrl_name = find_public_xbrl(zip_path)
    tree = load_xbrl_tree(zip_path, xbrl_name)
    nsmap = resolve_namespaces(tree, edinet_code)
    path_a = extract_path_a(tree, nsmap)
    path_b = extract_path_b(tree, nsmap)
    merged = merge_paths(path_a, path_b)
    unresolved = [k for k in ITEM_KEYS if merged.get(k, {}).get("value") is None]
    return ExtractResult(
        doc_id=doc_id,
        edinet_code=edinet_code,
        merged=merged,
        path_a=path_a,
        path_b=path_b,
        unresolved=unresolved,
    )


def fetch_and_extract(api_key: str, doc_id: str, edinet_code: str) -> ExtractResult:
    """Download (or reuse cached) XBRL zip and extract in one call."""
    zip_path = download_xbrl_zip(api_key, doc_id)
    return extract_from_zip(zip_path, edinet_code, doc_id)


# ---------------------------------------------------------------------------
# Restated EPS extraction (Path B Prior*YearDuration walk)
# ---------------------------------------------------------------------------
#
# Used by scripts.split_adjust to repair the stock-split mismatch documented
# in pre-research Step 5 / Step 7 (verification_results.md). The latest annual
# report's SummaryOfBusinessResults exposes the past 5 fiscal years' EPS as
# Prior{N}YearDuration; those values are already rebased to the post-split
# share count at filing time. Reading them gives us a per-fiscal-year mapping
# we can use to recompute PER without the basis mismatch yfinance introduces.

EPS_SUMMARY_ELEMENT = "BasicEarningsLossPerShareIFRSSummaryOfBusinessResults"

# (offset_from_latest, context_id). Latest report's CurrentYearDuration is
# offset 0; Prior{N} walks back exactly N fiscal years. EDINET reports
# typically expose 0..4 (latest + 4 priors = 5 years).
SUMMARY_CONTEXTS: list[tuple[int, str]] = [
    (0, "CurrentYearDuration"),
    (1, "Prior1YearDuration"),
    (2, "Prior2YearDuration"),
    (3, "Prior3YearDuration"),
    (4, "Prior4YearDuration"),
]


def extract_restated_eps_from_zip(
    zip_path: Path,
    edinet_code: str,
) -> dict[int, float]:
    """Return {offset_from_latest: eps} for every Prior*YearDuration found.

    Keys are integer offsets (0 = latest period, 1 = one year prior, …).
    Callers map offsets to fiscal year-end dates using the latest report's
    period_end. Returned values are in JPY/share (float).
    Empty dict means no SummaryOfBusinessResults EPS was found.
    """
    xbrl_name = find_public_xbrl(zip_path)
    tree = load_xbrl_tree(zip_path, xbrl_name)
    nsmap = resolve_namespaces(tree, edinet_code)
    out: dict[int, float] = {}
    for offset, ctx in SUMMARY_CONTEXTS:
        value, _unit, _dec = get_fact(tree, nsmap, "jpcrp_cor", EPS_SUMMARY_ELEMENT, ctx)
        if value is None:
            continue
        out[offset] = float(value)
    return out

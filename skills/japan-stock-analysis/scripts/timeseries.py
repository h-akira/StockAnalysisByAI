"""Annual time-series builder.

Successor of pre-research/edinet/step4_timeseries.py. Iterates over a
company's annual filings (resolved via doc_list), runs xbrl_extract on
each, and persists a per-company CSV under cache/derived/.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from scripts import paths
from scripts.doc_list import DocRecord, find_documents_for_sec_code
from scripts.xbrl_extract import ITEM_KEYS, fetch_and_extract

# Output column order: period_end (index) + 9 items + FreeCF.
ITEM_COLUMNS: list[str] = ITEM_KEYS + ["FreeCF"]


def timeseries_csv_path(sec_code: str) -> Path:
    return paths.DERIVED_DIR / f"timeseries_{sec_code}.csv"


def _typed_value(raw: str | None) -> float | int | None:
    """Convert XBRL string to int (JPY) or float (EPS). None passes through."""
    if raw is None:
        return None
    # EPS-like values contain '.'; everything else (JPY, shares) is integer.
    return float(raw) if "." in raw else int(raw)


def extract_row(
    api_key: str,
    doc: DocRecord,
    *,
    extra_mappings: dict[str, dict] | None = None,
) -> tuple[dict[str, float | int | None], list[str]]:
    """Run xbrl_extract on one filing and return (numeric row, unresolved items)."""
    result = fetch_and_extract(
        api_key, doc.doc_id, doc.edinet_code, extra_mappings=extra_mappings,
    )
    row: dict[str, float | int | None] = {}
    for key in ITEM_COLUMNS:
        v = result.merged.get(key, {}).get("value")
        row[key] = _typed_value(v)
    return row, result.unresolved


def build_timeseries(
    sec_code: str,
    api_key: str,
    *,
    limit: int | None = None,
    extra_mappings: dict[str, dict] | None = None,
) -> tuple[pd.DataFrame, list[str]]:
    """Build a multi-year DataFrame for one company.

    Returns (df, union_unresolved_items). ``union_unresolved_items`` aggregates
    unresolved item names across every year processed, so the caller can
    trigger escalation if the whitelist + extra_mappings still leave gaps.

    ``limit`` caps the number of filings processed (newest last, oldest first
    is the natural CSV order from doc_list); useful for incremental testing.
    """
    docs = find_documents_for_sec_code(sec_code)
    if not docs:
        raise ValueError(
            f"No annual reports (docType=120) found for sec_code {sec_code} "
            "in cache/documents/. Bootstrap may be incomplete for this period."
        )
    if limit is not None:
        docs = docs[-limit:]

    rows: list[dict] = []
    unresolved_union: set[str] = set()
    for doc in docs:
        items, unresolved = extract_row(api_key, doc, extra_mappings=extra_mappings)
        rows.append({"period_end": doc.period_end, **items})
        unresolved_union.update(unresolved)

    df = pd.DataFrame(rows).set_index("period_end").sort_index()
    return df, sorted(unresolved_union)


def save_timeseries(sec_code: str, df: pd.DataFrame) -> Path:
    paths.ensure_cache_dirs()
    out = timeseries_csv_path(sec_code)
    df.to_csv(out)
    return out

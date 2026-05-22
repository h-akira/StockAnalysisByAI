"""Per-company JSON export.

Writes `data_{sec_code}.json` to the caller's CWD. The schema is documented
in docs/json_schema.md and versioned via SCHEMA_VERSION.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from scripts import paths
from scripts.company_map import lookup as lookup_company
from scripts.doc_list import find_documents_for_sec_code
from scripts.metrics import metrics_csv_path
from scripts.split_adjust import SplitAdjustResult
from scripts.timeseries import timeseries_csv_path

SCHEMA_VERSION = "1.0"

FINANCIAL_KEYS = [
    "NetSales", "OperatingIncome", "ProfitLoss", "EarningsPerShare",
    "TotalAssets", "NetAssets", "InterestBearingDebt",
    "OperatingCF", "InvestingCF", "FinancingCF", "SharesOutstanding", "FreeCF",
]

METRIC_KEYS = [
    "OperatingMargin", "NetMargin", "ROE", "EquityRatio", "DERatio",
    "SalesGrowth", "ProfitGrowth", "BPS",
    "StockPrice", "EPSForPER", "PER", "PBR",
]


def data_json_path(sec_code: str) -> Path:
    return paths.output_dir() / f"data_{sec_code}.json"


def _to_jsonable(value) -> float | None:
    """Convert pandas/numpy scalars to JSON-friendly values. NaN -> None."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if pd.isna(value):
        return None
    return float(value) if isinstance(value, (int, float)) else value


def _row_to_dict(row: pd.Series, keys: list[str]) -> dict:
    return {k: _to_jsonable(row.get(k)) for k in keys}


def build_payload(
    sec_code: str,
    *,
    split_adjust: SplitAdjustResult | None,
    warnings: list[str],
) -> dict:
    """Assemble the data_{sec_code}.json payload from cache CSVs."""
    ts = pd.read_csv(timeseries_csv_path(sec_code), parse_dates=["period_end"]).set_index("period_end")
    mt = pd.read_csv(metrics_csv_path(sec_code), parse_dates=["period_end"]).set_index("period_end")

    company = lookup_company(sec_code) or {}
    edinet_code = company.get("edinet_code", "")
    company_name = company.get("filer_name", sec_code)

    # docID list: cache/documents may have far more years than the analyzed
    # window, but we surface only those that overlap the timeseries index so
    # the JSON stays scoped to the analyzed period_ends.
    try:
        docs = find_documents_for_sec_code(sec_code)
        ts_dates = {pe.date().isoformat() for pe in ts.index}
        source_doc_ids = [d.doc_id for d in docs if d.period_end in ts_dates]
    except Exception:
        source_doc_ids = []

    fiscal_years = []
    for pe in ts.index.sort_values():
        fiscal_years.append({
            "period_end": pe.date().isoformat(),
            "financials": _row_to_dict(ts.loc[pe], FINANCIAL_KEYS),
            "metrics": _row_to_dict(mt.loc[pe], METRIC_KEYS) if pe in mt.index else {},
        })

    return {
        "schema_version": SCHEMA_VERSION,
        "sec_code": sec_code,
        "company_name": company_name,
        "edinet_code": edinet_code,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_doc_ids": source_doc_ids,
        "split_adjust_source_doc_id": (split_adjust.source_doc_id if split_adjust else None),
        "fiscal_years": fiscal_years,
        "warnings": warnings,
    }


def write_data_json(
    sec_code: str,
    *,
    split_adjust: SplitAdjustResult | None,
    warnings: list[str],
) -> Path:
    payload = build_payload(sec_code, split_adjust=split_adjust, warnings=warnings)
    out = data_json_path(sec_code)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out

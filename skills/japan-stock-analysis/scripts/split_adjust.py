"""Stock-split adjustment via restated EPS from the latest annual report.

Method (a) selected after pre-research Step 7 verification: yfinance's
naive split-ratio division can disagree with EDINET's restated EPS by ~7%
for companies with active share buybacks (Sony 6758 FY2023 case). The
correct value lives in the latest annual report's SummaryOfBusinessResults
Prior*YearDuration contexts, which are already weighted-average rebased.

Cache shape: cache/split_adjust/{sec_code}.json
    {
      "sec_code": "6758",
      "source_doc_id": "S100W19Q",
      "source_period_end": "2025-03-31",
      "resolved_at": "2026-05-22T...",
      "restated_eps": {
        "2021-03-31": 167.35,
        "2022-03-31": 142.37,
        "2023-03-31": 162.71,
        "2024-03-31": 157.66,
        "2025-03-31": 188.71
      }
    }

The cache key is the source_doc_id of the latest report. If the latest
report changes (a new fiscal year was filed) the cache is rebuilt;
otherwise it is reused. Fiscal years older than the report's coverage
(typically 6+ years back) are simply absent from the map — callers should
treat them as NaN and warn the user, per init_plan.md §4.5 / pre-research Step 7
教訓 #3.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from scripts import paths
from scripts.xbrl_extract import (
    download_xbrl_zip,
    extract_restated_eps_from_zip,
)


@dataclass(frozen=True)
class SplitAdjustResult:
    sec_code: str
    source_doc_id: str
    source_period_end: str
    restated_eps: dict[str, float]   # ISO date string -> EPS
    eps_source: dict[str, str] = field(default_factory=dict)
    # ISO date string -> EPS_SUMMARY_ELEMENTS tag. Records which variant
    # (ifrs_basic / jgaap_basic / ifrs_diluted / jgaap_diluted) was actually
    # used per period_end so warnings can flag non-Basic fallbacks (ENH-002).

    def get(self, period_end: str | pd.Timestamp) -> float | None:
        """Look up restated EPS for a period_end. Returns None if out of range."""
        key = (
            period_end.date().isoformat()
            if isinstance(period_end, pd.Timestamp)
            else str(period_end)[:10]
        )
        return self.restated_eps.get(key)


def split_adjust_path(sec_code: str) -> Path:
    return paths.SPLIT_ADJUST_DIR / f"{sec_code}.json"


def _load_cached(sec_code: str) -> dict | None:
    p = split_adjust_path(sec_code)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _save_cache(sec_code: str, payload: dict) -> Path:
    paths.ensure_cache_dirs()
    p = split_adjust_path(sec_code)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def _offsets_to_period_ends(
    latest_period_end: pd.Timestamp,
    offsets: dict[int, float],
) -> dict[str, float]:
    """Convert {offset: eps} to {ISO date string: eps} using DateOffset(years=N)."""
    out: dict[str, float] = {}
    for offset, eps in offsets.items():
        pe = latest_period_end - pd.DateOffset(years=offset)
        out[pe.date().isoformat()] = eps
    return out


def _offset_tags_to_period_ends(
    latest_period_end: pd.Timestamp,
    tags: dict[int, str],
) -> dict[str, str]:
    """Same as _offsets_to_period_ends but for the audit-source tag dict."""
    out: dict[str, str] = {}
    for offset, tag in tags.items():
        pe = latest_period_end - pd.DateOffset(years=offset)
        out[pe.date().isoformat()] = tag
    return out


def resolve_split_adjust(
    sec_code: str,
    api_key: str,
    latest_doc_id: str,
    latest_edinet_code: str,
    latest_period_end: str,
) -> SplitAdjustResult:
    """Return the restated EPS mapping for one company.

    If the cache is fresh (cached source_doc_id == latest_doc_id) the cache
    is returned without touching the XBRL. Otherwise the latest report's
    XBRL is parsed (downloaded if absent), Prior*YearDuration EPS extracted,
    and the result persisted.
    """
    cached = _load_cached(sec_code)
    if cached and cached.get("source_doc_id") == latest_doc_id:
        return SplitAdjustResult(
            sec_code=cached["sec_code"],
            source_doc_id=cached["source_doc_id"],
            source_period_end=cached["source_period_end"],
            restated_eps=cached["restated_eps"],
            eps_source=cached.get("eps_source", {}),
        )

    zip_path = download_xbrl_zip(api_key, latest_doc_id)
    offsets, source_offsets = extract_restated_eps_from_zip(zip_path, latest_edinet_code)
    latest_pe_ts = pd.to_datetime(latest_period_end)
    restated = _offsets_to_period_ends(latest_pe_ts, offsets)
    eps_source = _offset_tags_to_period_ends(latest_pe_ts, source_offsets)

    payload = {
        "sec_code": sec_code,
        "source_doc_id": latest_doc_id,
        "source_period_end": latest_period_end,
        "resolved_at": datetime.now(timezone.utc).isoformat(),
        "restated_eps": restated,
        "eps_source": eps_source,
    }
    _save_cache(sec_code, payload)
    return SplitAdjustResult(
        sec_code=sec_code,
        source_doc_id=latest_doc_id,
        source_period_end=latest_period_end,
        restated_eps=restated,
        eps_source=eps_source,
    )

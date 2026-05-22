"""Document list lookup for a given securities code.

Lightweight counterpart of pre-research/edinet/step2_doc_list.py: assumes
documents_index has already been bootstrapped (see scripts/bootstrap.py)
and only filters the cached JSONs in cache/documents/*.json. No network.

Output shape mirrors the pre-research per-company CSV columns:
    edinet_code, filer_name, doc_id, doc_type_code,
    period_start, period_end, submit_date, xbrl_flag
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from scripts import paths
from scripts.company_map import lookup as lookup_company

DOC_TYPE_ANNUAL = "120"  # 有価証券報告書 (annual securities report)


class DocumentsNotBootstrappedError(FileNotFoundError):
    """Raised when cache/documents/ is empty — bootstrap has not been run."""


@dataclass(frozen=True)
class DocRecord:
    edinet_code: str
    filer_name: str
    doc_id: str
    doc_type_code: str
    period_start: str
    period_end: str
    submit_date: str
    xbrl_flag: str


def _iter_documents_jsons() -> list[Path]:
    if not paths.DOCUMENTS_DIR.exists():
        return []
    return sorted(paths.DOCUMENTS_DIR.glob("*.json"))


def find_documents_for_edinet_code(
    edinet_code: str,
    doc_type_code: str = DOC_TYPE_ANNUAL,
) -> list[DocRecord]:
    """Scan every cached date JSON and return matching documents.

    Filters: edinetCode == edinet_code AND docTypeCode == doc_type_code.
    Returns records sorted by period_end ascending. Empty list is a valid
    result (e.g. company has not filed anything in the cached window).
    """
    files = _iter_documents_jsons()
    if not files:
        raise DocumentsNotBootstrappedError(
            f"cache/documents/ is empty at {paths.DOCUMENTS_DIR}. "
            "Run: python3 ${CLAUDE_SKILL_DIR}/scripts/bootstrap.py fetch-documents --years 10"
        )
    hits: list[DocRecord] = []
    for fp in files:
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            # Corrupt cache entry — skip rather than abort the whole lookup;
            # the rest of the bootstrap-day cache is still usable.
            continue
        for r in data.get("results", []) or []:
            if r.get("edinetCode") != edinet_code:
                continue
            if r.get("docTypeCode") != doc_type_code:
                continue
            hits.append(DocRecord(
                edinet_code=r["edinetCode"],
                filer_name=r.get("filerName", ""),
                doc_id=r["docID"],
                doc_type_code=r.get("docTypeCode", ""),
                period_start=r.get("periodStart", ""),
                period_end=r.get("periodEnd", ""),
                submit_date=(r.get("submitDateTime", "") or "")[:10],
                xbrl_flag=r.get("xbrlFlag", ""),
            ))
    hits.sort(key=lambda d: d.period_end)
    return hits


def find_documents_for_sec_code(
    sec_code: str,
    doc_type_code: str = DOC_TYPE_ANNUAL,
) -> list[DocRecord]:
    """Look up a company by 4-digit sec_code and return its filings."""
    company = lookup_company(sec_code)
    if not company:
        raise ValueError(
            f"sec_code {sec_code!r} not found in company_map.csv. "
            "Run: python3 ${CLAUDE_SKILL_DIR}/scripts/bootstrap.py refresh-company-map"
        )
    return find_documents_for_edinet_code(company["edinet_code"], doc_type_code)

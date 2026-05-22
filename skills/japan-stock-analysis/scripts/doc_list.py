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
from datetime import date, timedelta
from pathlib import Path

from scripts import paths
from scripts.company_map import lookup as lookup_company

DOC_TYPE_ANNUAL = "120"  # 有価証券報告書 (annual securities report)

# Submission-window constants for the per-company gap detector. Mirror the
# pre-research step2_doc_list.py defaults that were validated by Step 2.
MONTHS_AFTER_FISCAL_END = 3
BUFFER_DAYS = 7


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


# ---------------------------------------------------------------------------
# Bootstrap-gap detection
# ---------------------------------------------------------------------------
#
# pre-research/edinet/step2_doc_list.py had build_scan_dates() that returned
# weekday submission windows for a single company's fiscal-month. Bootstrap
# in this Skill takes the simpler approach of pulling every weekday, but
# when we want to check "is this sec_code's history actually covered by
# what's cached?" we still need per-company windows. That's what this does.


def _fiscal_end_month(fiscal_month_jp: str) -> int:
    """Parse the Japanese fiscal_month field ('3月31日') into a month number."""
    return int(fiscal_month_jp.split("月", 1)[0])


def _submission_window(fiscal_end_m: int, fiscal_year: int) -> tuple[date, date]:
    """Per-fiscal-year submission window: filing deadline +/- BUFFER_DAYS."""
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


def build_expected_windows(
    sec_code: str,
    years: int = 10,
    today: date | None = None,
) -> list[date]:
    """Return weekday dates where this company's annual report should appear.

    Walks back ``years`` fiscal years from the latest closed submission
    window, mirroring pre-research step2_doc_list.build_scan_dates(). Weekends
    are skipped because EDINET returns 404 for them. Dates strictly in the
    future are dropped.
    """
    company = lookup_company(sec_code)
    if not company:
        raise ValueError(
            f"sec_code {sec_code!r} not found in company_map.csv. "
            "Run: python3 ${CLAUDE_SKILL_DIR}/scripts/bootstrap.py refresh-company-map"
        )
    fiscal_m = _fiscal_end_month(company.get("fiscal_month", "3月31日"))
    today_d = today or date.today()

    # Anchor on the most recent fiscal year whose window has already closed.
    anchor = today_d.year
    while _submission_window(fiscal_m, anchor)[1] > today_d:
        anchor -= 1

    dates: list[date] = []
    for year_offset in range(years):
        start, end = _submission_window(fiscal_m, anchor - year_offset)
        d = start
        while d <= end:
            if d.weekday() < 5 and d <= today_d:
                dates.append(d)
            d += timedelta(days=1)
    return sorted(set(dates))


def find_missing_windows(sec_code: str, years: int = 10, today: date | None = None) -> list[str]:
    """Return ISO date strings in the expected submission window NOT in cache.

    Used by pipeline.py to surface a structured 'needs_bootstrap' error when
    a company's annual reports could not be located. An empty list means the
    bootstrap fully covers the company's expected filings.
    """
    expected = build_expected_windows(sec_code, years=years, today=today)
    if not paths.DOCUMENTS_DIR.exists():
        return [d.isoformat() for d in expected]
    cached = {p.stem for p in paths.DOCUMENTS_DIR.glob("*.json")}
    return [d.isoformat() for d in expected if d.isoformat() not in cached]

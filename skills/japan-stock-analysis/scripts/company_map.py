"""Company master (EDINET code <-> securities code mapping).

Loader for cache/company_map.csv. The refresh path lives in
scripts/bootstrap.py (refresh-company-map subcommand) — this module is
read-only at runtime.

CSV schema:
    sec_code, edinet_code, filer_name, listing, fiscal_month, industry

Securities-code convention:
    EDINET stores 5-digit codes with a trailing zero (e.g. "72030" for 7203).
    User-facing 4-digit codes are accepted and padded on lookup.
"""

from __future__ import annotations

import csv
from typing import TypedDict

from scripts import paths


class CompanyRecord(TypedDict):
    sec_code: str
    edinet_code: str
    filer_name: str
    listing: str
    fiscal_month: str
    industry: str


class CompanyMapMissingError(FileNotFoundError):
    """Raised when company_map.csv has not been bootstrapped yet."""


def normalize_sec_code(sec_code: str) -> str:
    """Convert a user-facing 4-digit code to EDINET's 5-digit form."""
    if len(sec_code) == 4 and sec_code.isdigit():
        return sec_code + "0"
    return sec_code


def load_company_map() -> dict[str, CompanyRecord]:
    """Return {edinet-5-digit sec_code: CompanyRecord}. Raises if not bootstrapped."""
    if not paths.COMPANY_MAP.exists():
        raise CompanyMapMissingError(
            f"company_map.csv not found at {paths.COMPANY_MAP}. "
            "Run: python3 ${CLAUDE_SKILL_DIR}/scripts/bootstrap.py refresh-company-map"
        )
    with paths.COMPANY_MAP.open(encoding="utf-8") as f:
        return {row["sec_code"]: row for row in csv.DictReader(f)}  # type: ignore[misc]


def lookup(sec_code: str) -> CompanyRecord | None:
    """Look up a single company by 4- or 5-digit code. Returns None if absent."""
    return load_company_map().get(normalize_sec_code(sec_code))

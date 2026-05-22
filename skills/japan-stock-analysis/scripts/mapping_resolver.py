"""XBRL element mapping resolver (whitelist + AI escalation).

Implementation target: Phase P8 (full AI escalation flow). A no-op stub
that just reports "unresolved" can land alongside P3 so that the pipeline
type-checks; the LLM bridge proper lands in P8.

Strategy (see plan.md §4.4):
    1. Try whitelist (xbrl_extract.py).
    2. Check cache/mappings/{sec_code}.json.
    3. Escalate to LLM via SKILL.md handoff; persist result.
"""

from __future__ import annotations


def resolve_mappings(sec_code: str, unresolved: list[str]):
    raise NotImplementedError("mapping_resolver is planned for Phase P8")


def save_mappings(sec_code: str, mappings: dict) -> None:
    raise NotImplementedError("mapping save is planned for Phase P8")

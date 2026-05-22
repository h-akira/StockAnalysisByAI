"""Unit tests for scripts.doc_list.build_expected_windows and find_missing_windows.

The window logic is the per-company variant of pre-research step2's
build_scan_dates; verify shape, weekday filter, future-clipping, and the
gap detector that pipeline.py uses for needs_bootstrap.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from scripts import company_map, doc_list, paths


def _patch_company_and_docs(monkeypatch, tmp_path, fiscal_month: str = "3月31日"):
    # Stub lookup_company so the windows can be computed without a real CSV.
    monkeypatch.setattr(
        doc_list, "lookup_company",
        lambda sc: {"sec_code": sc + "0", "edinet_code": "Exxx", "filer_name": "TEST",
                    "listing": "上場", "fiscal_month": fiscal_month, "industry": "x"},
    )
    monkeypatch.setattr(paths, "DOCUMENTS_DIR", tmp_path)


# ---------- build_expected_windows ----------

def test_windows_for_march_fiscal_end_target_june(monkeypatch, tmp_path) -> None:
    _patch_company_and_docs(monkeypatch, tmp_path)
    # today = late August 2026 -> latest closed window is June 2026 (FY2025).
    dates = doc_list.build_expected_windows("7203", years=1, today=date(2026, 8, 31))

    assert all(d.weekday() < 5 for d in dates), "weekends must be excluded"
    months = {d.month for d in dates}
    assert months == {5, 6, 7}, "expected window: late May .. early July (June ±7 days)"


def test_windows_walks_back_requested_years(monkeypatch, tmp_path) -> None:
    _patch_company_and_docs(monkeypatch, tmp_path)
    dates = doc_list.build_expected_windows("7203", years=3, today=date(2026, 8, 31))
    years = {d.year for d in dates}
    # Three closed windows: 2024 (FY2023), 2025 (FY2024), 2026 (FY2025).
    assert years == {2024, 2025, 2026}


def test_windows_clip_future_dates(monkeypatch, tmp_path) -> None:
    _patch_company_and_docs(monkeypatch, tmp_path)
    today = date(2026, 6, 10)  # mid-window
    dates = doc_list.build_expected_windows("7203", years=1, today=today)
    assert max(dates) <= today


def test_windows_for_december_fiscal_end(monkeypatch, tmp_path) -> None:
    _patch_company_and_docs(monkeypatch, tmp_path, fiscal_month="12月31日")
    # December fiscal-end -> filing deadline March of the next calendar year.
    dates = doc_list.build_expected_windows("9999", years=1, today=date(2026, 8, 31))
    assert all(d.year == 2026 and d.month in (2, 3, 4) for d in dates)


def test_windows_raises_for_unknown_sec_code(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(doc_list, "lookup_company", lambda sc: None)
    with pytest.raises(ValueError):
        doc_list.build_expected_windows("9999", years=1)


# ---------- find_missing_windows ----------

def test_find_missing_when_cache_empty(monkeypatch, tmp_path) -> None:
    _patch_company_and_docs(monkeypatch, tmp_path)
    missing = doc_list.find_missing_windows("7203", years=1, today=date(2026, 8, 31))
    assert len(missing) > 0
    # All ISO-formatted, all weekdays.
    for s in missing:
        d = date.fromisoformat(s)
        assert d.weekday() < 5


def test_find_missing_empty_when_cache_complete(monkeypatch, tmp_path) -> None:
    _patch_company_and_docs(monkeypatch, tmp_path)
    expected = doc_list.build_expected_windows("7203", years=1, today=date(2026, 8, 31))
    for d in expected:
        (tmp_path / f"{d.isoformat()}.json").write_text(json.dumps({"results": []}))
    missing = doc_list.find_missing_windows("7203", years=1, today=date(2026, 8, 31))
    assert missing == []

"""Unit tests for scripts.doc_list.

The doc_list module only reads cache/documents/*.json — fully exercisable
without network. Tests redirect paths.DOCUMENTS_DIR to a tmp_path.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import doc_list, paths


def _write_doc_json(dir_: Path, date: str, results: list[dict]) -> None:
    (dir_ / f"{date}.json").write_text(
        json.dumps({"metadata": {"status": "200"}, "results": results}, ensure_ascii=False),
        encoding="utf-8",
    )


def _patch_docs(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "DOCUMENTS_DIR", tmp_path)


def test_empty_cache_raises_not_bootstrapped(monkeypatch, tmp_path) -> None:
    _patch_docs(monkeypatch, tmp_path)
    with pytest.raises(doc_list.DocumentsNotBootstrappedError):
        doc_list.find_documents_for_edinet_code("E02144")


def test_filter_by_edinet_code_and_doc_type(monkeypatch, tmp_path) -> None:
    _patch_docs(monkeypatch, tmp_path)
    _write_doc_json(tmp_path, "2026-06-25", [
        {"edinetCode": "E02144", "docID": "S100AAAA", "docTypeCode": "120",
         "filerName": "トヨタ", "periodStart": "2025-04-01", "periodEnd": "2026-03-31",
         "submitDateTime": "2026-06-25 09:00", "xbrlFlag": "1"},
        {"edinetCode": "E02144", "docID": "S100BBBB", "docTypeCode": "140",  # quarterly
         "filerName": "トヨタ", "periodStart": "2025-04-01", "periodEnd": "2025-06-30",
         "submitDateTime": "2025-08-12 09:00", "xbrlFlag": "1"},
        {"edinetCode": "E01777", "docID": "S100CCCC", "docTypeCode": "120",  # different filer
         "filerName": "ソニー", "periodStart": "2025-04-01", "periodEnd": "2026-03-31",
         "submitDateTime": "2026-06-25 09:00", "xbrlFlag": "1"},
    ])
    hits = doc_list.find_documents_for_edinet_code("E02144")
    assert [h.doc_id for h in hits] == ["S100AAAA"]
    assert hits[0].period_end == "2026-03-31"
    assert hits[0].submit_date == "2026-06-25"


def test_sorted_by_period_end(monkeypatch, tmp_path) -> None:
    _patch_docs(monkeypatch, tmp_path)
    _write_doc_json(tmp_path, "2024-06-25", [
        {"edinetCode": "E02144", "docID": "OLD", "docTypeCode": "120",
         "filerName": "トヨタ", "periodEnd": "2024-03-31", "submitDateTime": "2024-06-25"},
    ])
    _write_doc_json(tmp_path, "2026-06-25", [
        {"edinetCode": "E02144", "docID": "NEW", "docTypeCode": "120",
         "filerName": "トヨタ", "periodEnd": "2026-03-31", "submitDateTime": "2026-06-25"},
    ])
    hits = doc_list.find_documents_for_edinet_code("E02144")
    assert [h.doc_id for h in hits] == ["OLD", "NEW"]


def test_corrupt_json_is_skipped(monkeypatch, tmp_path) -> None:
    _patch_docs(monkeypatch, tmp_path)
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    _write_doc_json(tmp_path, "2026-06-25", [
        {"edinetCode": "E02144", "docID": "OK", "docTypeCode": "120",
         "filerName": "トヨタ", "periodEnd": "2026-03-31", "submitDateTime": "2026-06-25"},
    ])
    hits = doc_list.find_documents_for_edinet_code("E02144")
    assert [h.doc_id for h in hits] == ["OK"]


def test_404_marker_yields_empty_results(monkeypatch, tmp_path) -> None:
    _patch_docs(monkeypatch, tmp_path)
    # bootstrap writes {"metadata": {"status": "404"}, "results": []} on 404.
    _write_doc_json(tmp_path, "2025-12-31", [])
    hits = doc_list.find_documents_for_edinet_code("E02144")
    assert hits == []

"""Unit tests for scripts.bootstrap.

Network-free: only pure functions and the file-cache path are exercised.
Real EDINET fetches are exercised manually (see plan.md §5 P2 closing).
"""

from __future__ import annotations

import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from scripts import bootstrap, paths


# ---------- build_weekdays ----------

def test_build_weekdays_excludes_weekends() -> None:
    today = date(2026, 5, 22)  # Friday
    days = bootstrap.build_weekdays(1, today=today)
    assert all(d.weekday() < 5 for d in days)
    assert days[-1] == today
    assert days[0] == date(2025, 5, 23)  # one year +1 day back, walked to first weekday


def test_build_weekdays_count_one_year_is_about_260() -> None:
    today = date(2026, 5, 22)
    days = bootstrap.build_weekdays(1, today=today)
    # 1 year of weekdays is ~260 (252-262 depending on calendar).
    assert 250 <= len(days) <= 265


def test_build_weekdays_rejects_zero() -> None:
    with pytest.raises(ValueError):
        bootstrap.build_weekdays(0)


# ---------- chunk_dates ----------

def test_chunk_dates_partitions_without_loss() -> None:
    sample = [date(2026, 1, 1) for _ in range(100)]
    parts = [bootstrap.chunk_dates(sample, k, 4) for k in range(4)]
    assert sum(len(p) for p in parts) == len(sample)
    # Sizes are roughly equal.
    assert max(len(p) for p in parts) - min(len(p) for p in parts) <= 1


def test_chunk_dates_rejects_bad_spec() -> None:
    with pytest.raises(ValueError):
        bootstrap.chunk_dates([], 0, 0)
    with pytest.raises(ValueError):
        bootstrap.chunk_dates([], 3, 3)


def test_parse_chunk_spec_ok_and_bad() -> None:
    assert bootstrap.parse_chunk_spec("0/3") == (0, 3)
    assert bootstrap.parse_chunk_spec("2/3") == (2, 3)
    with pytest.raises(Exception):
        bootstrap.parse_chunk_spec("3/3")
    with pytest.raises(Exception):
        bootstrap.parse_chunk_spec("abc")
    with pytest.raises(Exception):
        bootstrap.parse_chunk_spec("1/0")


# ---------- fetch_and_cache ----------

def _patch_cache_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "DOCUMENTS_DIR", tmp_path / "documents")
    (tmp_path / "documents").mkdir()


def test_fetch_and_cache_writes_payload(monkeypatch, tmp_path) -> None:
    _patch_cache_dir(monkeypatch, tmp_path)

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {"metadata": {"status": "200"}, "results": [{"docID": "X"}]}

    with patch.object(bootstrap.requests, "get", return_value=fake_resp) as get_mock:
        result = bootstrap.fetch_and_cache("KEY", date(2026, 5, 22))

    assert result == "fetched"
    out = tmp_path / "documents" / "2026-05-22.json"
    assert out.exists()
    body = json.loads(out.read_text())
    assert body["results"][0]["docID"] == "X"
    get_mock.assert_called_once()


def test_fetch_and_cache_skips_existing(monkeypatch, tmp_path) -> None:
    _patch_cache_dir(monkeypatch, tmp_path)
    existing = tmp_path / "documents" / "2026-05-22.json"
    existing.write_text('{"results": []}')

    with patch.object(bootstrap.requests, "get") as get_mock:
        result = bootstrap.fetch_and_cache("KEY", date(2026, 5, 22))

    assert result == "skipped"
    get_mock.assert_not_called()


def test_fetch_and_cache_404_writes_empty_marker(monkeypatch, tmp_path) -> None:
    _patch_cache_dir(monkeypatch, tmp_path)

    fake_resp = MagicMock()
    fake_resp.status_code = 404

    with patch.object(bootstrap.requests, "get", return_value=fake_resp):
        result = bootstrap.fetch_and_cache("KEY", date(2026, 5, 23))  # Saturday-ish

    assert result == "fetched"
    body = json.loads((tmp_path / "documents" / "2026-05-23.json").read_text())
    assert body["results"] == []
    assert body["metadata"]["status"] == "404"


def test_fetch_documents_json_retries_429_then_succeeds(monkeypatch, tmp_path) -> None:
    """429 on first attempt should not abort — retry and succeed."""
    _patch_cache_dir(monkeypatch, tmp_path)
    rate_limited = MagicMock(status_code=429)
    ok = MagicMock(status_code=200)
    ok.json.return_value = {"metadata": {"status": "200"}, "results": []}

    # Skip the sleep so the test is fast.
    monkeypatch.setattr(bootstrap.time, "sleep", lambda _: None)
    with patch.object(bootstrap.requests, "get", side_effect=[rate_limited, ok]):
        out = bootstrap.fetch_documents_json("KEY", date(2026, 5, 22), max_retries=3, backoff_seconds=0)
    assert out["metadata"]["status"] == "200"


def test_fetch_documents_json_eventually_raises_on_persistent_429(monkeypatch, tmp_path) -> None:
    """Persistent 429 across all retries should raise (caller counts via --max-errors)."""
    _patch_cache_dir(monkeypatch, tmp_path)
    rate_limited = MagicMock(status_code=429)
    rate_limited.raise_for_status.side_effect = bootstrap.requests.HTTPError("429")

    monkeypatch.setattr(bootstrap.time, "sleep", lambda _: None)
    with patch.object(bootstrap.requests, "get", return_value=rate_limited):
        with pytest.raises(bootstrap.requests.HTTPError):
            bootstrap.fetch_documents_json("KEY", date(2026, 5, 22), max_retries=2, backoff_seconds=0)


# ---------- build_company_map ----------

def test_build_company_map_filters_unlisted_rows() -> None:
    rows = [
        {"証券コード": "72030", "ＥＤＩＮＥＴコード": "E02144", "提出者名": "トヨタ自動車",
         "上場区分": "上場", "決算日": "3月31日", "提出者業種": "輸送用機器"},
        {"証券コード": "", "ＥＤＩＮＥＴコード": "E99999", "提出者名": "投資信託",
         "上場区分": "", "決算日": "", "提出者業種": ""},
    ]
    out = bootstrap.build_company_map(rows)
    assert len(out) == 1
    assert out[0]["sec_code"] == "72030"
    assert out[0]["edinet_code"] == "E02144"

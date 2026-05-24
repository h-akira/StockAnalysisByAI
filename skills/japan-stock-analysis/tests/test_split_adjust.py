"""Unit tests for scripts.split_adjust.

Network-free: only the offset→period_end mapping, cache I/O, and
SplitAdjustResult.get() are exercised. XBRL parsing itself is covered
indirectly by pre-research Step 7 (verification_results.md) — the Sony
6758 FY2023 expected restated EPS of 162.71 is encoded here as a
fixture-style regression test on the offset arithmetic.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from scripts import paths, split_adjust


def _patch_split_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "SPLIT_ADJUST_DIR", tmp_path)


# ---------- offset -> period_end ----------

def test_offsets_to_period_ends_walks_back_by_years() -> None:
    latest = pd.Timestamp("2025-03-31")
    offsets = {0: 188.71, 1: 157.66, 2: 162.71, 3: 142.37, 4: 167.35}
    out = split_adjust._offsets_to_period_ends(latest, offsets)
    # Sony 6758 expected mapping straight from pre-research Step 7.
    assert out == {
        "2025-03-31": 188.71,
        "2024-03-31": 157.66,
        "2023-03-31": 162.71,
        "2022-03-31": 142.37,
        "2021-03-31": 167.35,
    }


def test_offsets_handles_leap_year_safely() -> None:
    # March 31 stays March 31 across years; the DateOffset(years=N) path
    # in _offsets_to_period_ends must not slip to March 30.
    latest = pd.Timestamp("2024-03-31")
    offsets = {0: 1.0, 1: 1.0, 4: 1.0}
    out = split_adjust._offsets_to_period_ends(latest, offsets)
    assert set(out.keys()) == {"2024-03-31", "2023-03-31", "2020-03-31"}


# ---------- SplitAdjustResult.get ----------

def test_get_accepts_str_or_timestamp() -> None:
    r = split_adjust.SplitAdjustResult(
        sec_code="6758", source_doc_id="S100W19Q", source_period_end="2025-03-31",
        restated_eps={"2023-03-31": 162.71, "2024-03-31": 157.66},
    )
    assert r.get("2023-03-31") == 162.71
    assert r.get(pd.Timestamp("2023-03-31")) == 162.71
    # Beyond-window period returns None — caller treats as NaN per init_plan.md §4.5.
    assert r.get("2010-03-31") is None


# ---------- cache I/O ----------

def test_save_then_load_roundtrip(monkeypatch, tmp_path) -> None:
    _patch_split_dir(monkeypatch, tmp_path)
    payload = {
        "sec_code": "6758",
        "source_doc_id": "S100W19Q",
        "source_period_end": "2025-03-31",
        "resolved_at": "2026-05-22T00:00:00+00:00",
        "restated_eps": {"2023-03-31": 162.71},
    }
    split_adjust._save_cache("6758", payload)

    loaded = split_adjust._load_cached("6758")
    assert loaded == payload


def test_load_missing_returns_none(monkeypatch, tmp_path) -> None:
    _patch_split_dir(monkeypatch, tmp_path)
    assert split_adjust._load_cached("9999") is None


def test_load_corrupt_returns_none(monkeypatch, tmp_path) -> None:
    _patch_split_dir(monkeypatch, tmp_path)
    (tmp_path / "6758.json").write_text("{not json")
    assert split_adjust._load_cached("6758") is None


# ---------- resolve_split_adjust uses cache when doc_id matches ----------

def test_resolve_uses_cache_when_source_doc_id_matches(monkeypatch, tmp_path) -> None:
    _patch_split_dir(monkeypatch, tmp_path)
    cached = {
        "sec_code": "6758",
        "source_doc_id": "S100W19Q",
        "source_period_end": "2025-03-31",
        "resolved_at": "2026-05-22T00:00:00+00:00",
        "restated_eps": {"2023-03-31": 162.71, "2025-03-31": 188.71},
    }
    (tmp_path / "6758.json").write_text(json.dumps(cached), encoding="utf-8")

    # If the cache is honored, neither download_xbrl_zip nor
    # extract_restated_eps_from_zip should be called — patch them to fail.
    monkeypatch.setattr(
        split_adjust, "download_xbrl_zip",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("cache miss")),
    )
    monkeypatch.setattr(
        split_adjust, "extract_restated_eps_from_zip",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("cache miss")),
    )

    result = split_adjust.resolve_split_adjust(
        sec_code="6758", api_key="KEY",
        latest_doc_id="S100W19Q", latest_edinet_code="E01777",
        latest_period_end="2025-03-31",
    )
    assert result.get("2023-03-31") == 162.71
    assert result.source_doc_id == "S100W19Q"


def test_resolve_rebuilds_when_source_doc_id_changes(monkeypatch, tmp_path) -> None:
    _patch_split_dir(monkeypatch, tmp_path)
    stale = {
        "sec_code": "6758",
        "source_doc_id": "OLD_DOC",
        "source_period_end": "2024-03-31",
        "resolved_at": "2025-06-25T00:00:00+00:00",
        "restated_eps": {"2024-03-31": 999.99},
    }
    (tmp_path / "6758.json").write_text(json.dumps(stale), encoding="utf-8")

    monkeypatch.setattr(split_adjust, "download_xbrl_zip", lambda *a, **kw: "fake.zip")
    monkeypatch.setattr(
        split_adjust, "extract_restated_eps_from_zip",
        lambda *a, **kw: {0: 188.71, 2: 162.71},
    )

    result = split_adjust.resolve_split_adjust(
        sec_code="6758", api_key="KEY",
        latest_doc_id="NEW_DOC", latest_edinet_code="E01777",
        latest_period_end="2025-03-31",
    )
    assert result.source_doc_id == "NEW_DOC"
    assert result.get("2025-03-31") == 188.71
    assert result.get("2023-03-31") == 162.71
    # Stale value must be gone.
    assert result.get("2024-03-31") is None


# ---------- regression: metrics.compute_metrics uses restated EPS for PER ----------

def test_compute_metrics_uses_split_adjusted_eps() -> None:
    from scripts.metrics import compute_metrics

    df = pd.DataFrame(
        {
            "NetSales": [1e12, 1e12],
            "OperatingIncome": [1e11, 1e11],
            "ProfitLoss": [1e11, 1e11],
            "TotalAssets": [5e12, 5e12],
            "NetAssets": [2e12, 2e12],
            "InterestBearingDebt": [1e12, 1e12],
            "EarningsPerShare": [758.38, 188.71],  # raw FY2023 and FY2025 (Sony)
            "SharesOutstanding": [1e9, 5e9],
        },
        index=pd.to_datetime(["2023-03-31", "2025-03-31"]),
    )
    prices = pd.Series([2397.0, 3765.0], index=df.index)
    restated = pd.Series([162.71, 188.71], index=df.index)  # Step 7 expected

    m = compute_metrics(df, prices, eps_for_per=restated)
    # PER should follow the restated EPS, not the raw one.
    assert m.loc["2023-03-31", "PER"] == pytest.approx(2397.0 / 162.71, rel=1e-6)
    assert m.loc["2025-03-31", "PER"] == pytest.approx(3765.0 / 188.71, rel=1e-6)

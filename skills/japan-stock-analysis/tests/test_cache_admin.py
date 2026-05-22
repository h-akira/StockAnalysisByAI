"""Unit tests for scripts.cache_admin clear and per-type primitives.

The CLI is tested via collect_info / clear_type / clear_sec_code / clear_all
helpers and via main() with a redirected paths module.
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout

import pytest

from scripts import cache_admin, paths


def _patch_dirs(monkeypatch, tmp_path):
    """Redirect every cache dir under a fresh tmp_path."""
    derived = tmp_path / "derived"
    prices = tmp_path / "prices"
    mappings = tmp_path / "mappings"
    split = tmp_path / "split_adjust"
    documents = tmp_path / "documents"
    xbrl = tmp_path / "xbrl"
    for d in (derived, prices, mappings, split, documents, xbrl):
        d.mkdir()
    company_map = tmp_path / "company_map.csv"
    company_map.write_text("sec_code,edinet_code\n")

    monkeypatch.setattr(paths, "DERIVED_DIR", derived)
    monkeypatch.setattr(paths, "PRICES_DIR", prices)
    monkeypatch.setattr(paths, "MAPPINGS_DIR", mappings)
    monkeypatch.setattr(paths, "SPLIT_ADJUST_DIR", split)
    monkeypatch.setattr(paths, "DOCUMENTS_DIR", documents)
    monkeypatch.setattr(paths, "XBRL_DIR", xbrl)
    monkeypatch.setattr(paths, "COMPANY_MAP", company_map)

    # cache_admin captured these at import time; redirect the dict too.
    monkeypatch.setattr(cache_admin, "CHEAP_TYPES", {
        "derived": (derived, "*.csv"),
        "prices": (prices, "*.csv"),
        "mappings": (mappings, "*.json"),
        "split-adjust": (split, "*.json"),
    })
    monkeypatch.setattr(cache_admin, "EXPENSIVE_TYPES", {
        "documents": (documents, "*.json"),
        "xbrl": (xbrl, "*.zip"),
    })
    monkeypatch.setattr(cache_admin, "_PER_SEC_FILES", {
        "derived": lambda sc: [derived / f"timeseries_{sc}.csv", derived / f"metrics_{sc}.csv"],
        "prices": lambda sc: [prices / f"{sc}.csv"],
        "mappings": lambda sc: [mappings / f"{sc}.json"],
        "split-adjust": lambda sc: [split / f"{sc}.json"],
    })
    return tmp_path


def _seed_sec_code(tmp_path, sec_code: str) -> list:
    files = [
        tmp_path / "derived" / f"timeseries_{sec_code}.csv",
        tmp_path / "derived" / f"metrics_{sec_code}.csv",
        tmp_path / "prices" / f"{sec_code}.csv",
        tmp_path / "mappings" / f"{sec_code}.json",
        tmp_path / "split_adjust" / f"{sec_code}.json",
    ]
    for p in files:
        p.write_text("x")
    return files


# ---------- clear_type primitive ----------

def test_clear_type_removes_only_pattern_matching_files(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    (tmp_path / "derived" / "a.csv").write_text("x")
    (tmp_path / "derived" / "b.csv").write_text("x")
    (tmp_path / "derived" / "keep.txt").write_text("x")

    removed = cache_admin.clear_type("derived")
    assert len(removed) == 2
    assert (tmp_path / "derived" / "keep.txt").exists()


def test_clear_type_rejects_unknown(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    with pytest.raises(ValueError):
        cache_admin.clear_type("nonsense")


# ---------- clear_sec_code ----------

def test_clear_sec_code_removes_all_per_sec_files(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    _seed_sec_code(tmp_path, "6758")

    removed = cache_admin.clear_sec_code("6758")
    assert len(removed) == 5
    # Files are gone.
    for name in ["timeseries_6758.csv", "metrics_6758.csv"]:
        assert not (tmp_path / "derived" / name).exists()


def test_clear_sec_code_respects_types_subset(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    _seed_sec_code(tmp_path, "6758")

    removed = cache_admin.clear_sec_code("6758", types=["prices"])
    assert removed == [str(tmp_path / "prices" / "6758.csv")]
    # derived/mappings/split-adjust files survive.
    assert (tmp_path / "derived" / "timeseries_6758.csv").exists()
    assert (tmp_path / "split_adjust" / "6758.json").exists()


def test_clear_sec_code_rejects_unknown_type(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    with pytest.raises(ValueError):
        cache_admin.clear_sec_code("6758", types=["wat"])


# ---------- clear_all ----------

def test_clear_all_wipes_every_cache(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    (tmp_path / "derived" / "x.csv").write_text("x")
    (tmp_path / "documents" / "2024-01-01.json").write_text("{}")
    (tmp_path / "xbrl" / "abc.zip").write_bytes(b"x")
    paths.COMPANY_MAP.write_text("y")

    removed = cache_admin.clear_all()
    # Each seeded file plus the company_map row -> at least 4 removed.
    assert len(removed) >= 4
    assert not (tmp_path / "derived" / "x.csv").exists()
    assert not paths.COMPANY_MAP.exists()


# ---------- CLI main() — flag-matrix smoke ----------

def _run_main(argv: list[str]) -> tuple[int, dict]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cache_admin.main(argv)
    return rc, json.loads(buf.getvalue())


def test_main_clear_requires_mode(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    rc, body = _run_main(["clear"])
    assert rc != 0
    assert body["status"] == "error"
    assert "specify one of" in body["reason"]


def test_main_clear_documents_requires_confirm(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    (tmp_path / "documents" / "2024-01-01.json").write_text("{}")

    rc, body = _run_main(["clear", "--documents"])
    assert rc != 0
    assert body["status"] == "error"
    assert "--confirm" in body["reason"]
    # File survived.
    assert (tmp_path / "documents" / "2024-01-01.json").exists()


def test_main_clear_documents_with_confirm_proceeds(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    f = tmp_path / "documents" / "2024-01-01.json"
    f.write_text("{}")

    rc, body = _run_main(["clear", "--documents", "--confirm"])
    assert rc == 0
    assert body["status"] == "success"
    assert body["types"] == ["documents"]
    assert not f.exists()


def test_main_clear_all_requires_confirm(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    rc, body = _run_main(["clear", "--all"])
    assert rc != 0
    assert "--confirm" in body["reason"]


def test_main_clear_modes_are_mutually_exclusive(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    rc, body = _run_main(["clear", "--derived", "--sec-code", "6758"])
    assert rc != 0
    assert "mutually exclusive" in body["reason"]


def test_main_clear_sec_code_default_clears_all_per_sec_types(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    _seed_sec_code(tmp_path, "6758")

    rc, body = _run_main(["clear", "--sec-code", "6758"])
    assert rc == 0
    assert body["status"] == "success"
    assert body["removed_count"] == 5


def test_main_clear_sec_code_with_types_subset(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    _seed_sec_code(tmp_path, "6758")

    rc, body = _run_main(["clear", "--sec-code", "6758", "--types", "derived,prices"])
    assert rc == 0
    # 2 derived + 1 prices = 3
    assert body["removed_count"] == 3
    assert (tmp_path / "mappings" / "6758.json").exists()

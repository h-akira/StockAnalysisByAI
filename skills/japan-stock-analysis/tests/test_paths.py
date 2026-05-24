"""Smoke tests for scripts.paths.

Phase P1: only verify path resolution is consistent (no I/O, no network).
Substantial test coverage lands in Phase P7.
"""

from __future__ import annotations

from pathlib import Path

from scripts import paths


def test_skill_root_contains_scripts() -> None:
    assert (paths.SKILL_ROOT / "scripts").is_dir()


def test_output_dir_env_var_override(tmp_path, monkeypatch) -> None:
    """JAPAN_STOCK_OUTPUT_DIR env var wins over CWD when it points to an existing dir."""
    monkeypatch.setenv(paths.OUTPUT_DIR_ENV_VAR, str(tmp_path))
    assert paths.output_dir() == tmp_path


def test_output_dir_env_var_ignored_when_dir_missing(tmp_path, monkeypatch) -> None:
    """Bogus override path falls back to Path.cwd() rather than crashing."""
    missing = tmp_path / "does_not_exist"
    monkeypatch.setenv(paths.OUTPUT_DIR_ENV_VAR, str(missing))
    assert paths.output_dir() == Path.cwd()


def test_cache_paths_under_skill_root() -> None:
    for p in (
        paths.CACHE_DIR,
        paths.DOCUMENTS_DIR,
        paths.XBRL_DIR,
        paths.DERIVED_DIR,
        paths.PRICES_DIR,
        paths.MAPPINGS_DIR,
        paths.COMPANY_MAP,
    ):
        assert paths.SKILL_ROOT in p.parents or p == paths.CACHE_DIR or p.parent == paths.CACHE_DIR


def test_output_dir_is_cwd() -> None:
    assert paths.output_dir() == Path.cwd()


def test_ensure_cache_dirs_is_idempotent(tmp_path, monkeypatch) -> None:
    # Redirect cache dirs to tmp_path so the test does not touch real cache.
    monkeypatch.setattr(paths, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(paths, "DOCUMENTS_DIR", tmp_path / "cache" / "documents")
    monkeypatch.setattr(paths, "XBRL_DIR", tmp_path / "cache" / "xbrl")
    monkeypatch.setattr(paths, "DERIVED_DIR", tmp_path / "cache" / "derived")
    monkeypatch.setattr(paths, "PRICES_DIR", tmp_path / "cache" / "prices")
    monkeypatch.setattr(paths, "MAPPINGS_DIR", tmp_path / "cache" / "mappings")

    paths.ensure_cache_dirs()
    paths.ensure_cache_dirs()  # idempotent
    assert (tmp_path / "cache" / "documents").is_dir()

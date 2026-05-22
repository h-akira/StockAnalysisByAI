"""Smoke tests for scripts.config.

Phase P1: verify missing-file and malformed-JSON error paths so that
SKILL.md can rely on stable ConfigError messages.
"""

from __future__ import annotations

import json

import pytest

from scripts.config import ConfigError, load_edinet_config


def test_missing_file_raises(tmp_path) -> None:
    missing = tmp_path / "nope.json"
    with pytest.raises(ConfigError, match="not found"):
        load_edinet_config(missing)


def test_invalid_json_raises(tmp_path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(ConfigError, match="not valid JSON"):
        load_edinet_config(bad)


def test_missing_api_key_raises(tmp_path) -> None:
    p = tmp_path / "no_key.json"
    p.write_text(json.dumps({"edinet": {}}))
    with pytest.raises(ConfigError, match="missing edinet.api_key"):
        load_edinet_config(p)


def test_empty_api_key_raises(tmp_path) -> None:
    p = tmp_path / "empty_key.json"
    p.write_text(json.dumps({"edinet": {"api_key": "   "}}))
    with pytest.raises(ConfigError, match="non-empty string"):
        load_edinet_config(p)


def test_valid_config_loads(tmp_path) -> None:
    p = tmp_path / "good.json"
    p.write_text(json.dumps({"edinet": {"api_key": "abc"}}))
    cfg = load_edinet_config(p)
    assert cfg.api_key == "abc"

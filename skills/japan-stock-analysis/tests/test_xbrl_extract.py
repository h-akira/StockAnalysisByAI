"""Unit tests for scripts.xbrl_extract.

Network-free tests cover the pure merge logic and the unresolved-list
calculation. End-to-end XBRL parsing is exercised in pipeline integration
testing (Phase P3 closing) and via fixtures in Phase P7.
"""

from __future__ import annotations

from scripts import xbrl_extract


def test_merge_picks_path_a_when_available() -> None:
    path_a = {k: {"value": "1", "source": "a"} for k in xbrl_extract.ITEM_KEYS}
    path_b = {k: {"value": "2", "source": "b"} for k in xbrl_extract.ITEM_KEYS}
    merged = xbrl_extract.merge_paths(path_a, path_b)
    assert all(merged[k]["path"] == "A" for k in xbrl_extract.ITEM_KEYS)


def test_merge_falls_back_to_path_b_when_a_is_none() -> None:
    path_a = {k: {"value": None, "source": "?"} for k in xbrl_extract.ITEM_KEYS}
    path_b = {k: {"value": "2", "source": "b"} for k in xbrl_extract.ITEM_KEYS}
    merged = xbrl_extract.merge_paths(path_a, path_b)
    for k in xbrl_extract.ITEM_KEYS:
        assert merged[k]["value"] == "2"
        assert merged[k]["path"] == "B"


def test_merge_marks_both_missing_as_none_with_path_none() -> None:
    path_a = {k: {"value": None} for k in xbrl_extract.ITEM_KEYS}
    path_b = {k: {"value": None} for k in xbrl_extract.ITEM_KEYS}
    merged = xbrl_extract.merge_paths(path_a, path_b)
    for k in xbrl_extract.ITEM_KEYS:
        assert merged[k]["value"] is None
        assert merged[k]["path"] is None


def test_merge_computes_free_cf_when_both_cf_present() -> None:
    path_a = {k: {"value": None} for k in xbrl_extract.ITEM_KEYS}
    path_b = {k: {"value": None} for k in xbrl_extract.ITEM_KEYS}
    path_b["OperatingCF"] = {"value": "100", "source": "b"}
    path_b["InvestingCF"] = {"value": "-30", "source": "b"}
    merged = xbrl_extract.merge_paths(path_a, path_b)
    assert merged["FreeCF"]["value"] == "70"
    assert merged["FreeCF"]["path"] == "computed"


def test_merge_marks_free_cf_none_when_either_cf_missing() -> None:
    path_a = {k: {"value": None} for k in xbrl_extract.ITEM_KEYS}
    path_b = {k: {"value": None} for k in xbrl_extract.ITEM_KEYS}
    path_b["OperatingCF"] = {"value": "100", "source": "b"}
    # InvestingCF stays None
    merged = xbrl_extract.merge_paths(path_a, path_b)
    assert merged["FreeCF"]["value"] is None
    assert merged["FreeCF"]["path"] is None

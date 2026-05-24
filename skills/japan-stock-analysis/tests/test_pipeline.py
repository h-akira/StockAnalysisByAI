"""End-to-end pipeline test against XBRL fixtures (no network).

cmd_analyze normally talks to EDINET (XBRL download) and Yahoo Finance.
For an offline test we redirect every cache directory to tmp_path,
short-circuit download_xbrl_zip to return the fixture, and stub yfinance
with a synthetic history. The 9-line-item extraction itself runs against
the real fixture, so this is a meaningful integration check.
"""

from __future__ import annotations

import io
import json
import shutil
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from scripts import (
    cache_admin,
    config,
    json_export,
    paths,
    pipeline,
    split_adjust,
    stock_price,
    xbrl_extract,
)

FIXTURES = Path(__file__).parent / "fixtures"
TOYOTA_FIXTURE = FIXTURES / "S100VWVY.zip"


def _build_isolated_cache(tmp_path: Path) -> None:
    """Create every cache subdir under tmp_path with the same names."""
    for sub in ("documents", "xbrl", "derived", "prices", "mappings", "split_adjust"):
        (tmp_path / sub).mkdir()


def _stub_paths(monkeypatch, tmp_path: Path) -> Path:
    """Redirect paths.* to a clean tmp_path skeleton; set CWD output_dir there."""
    _build_isolated_cache(tmp_path)

    company_map = tmp_path / "company_map.csv"
    company_map.write_text(
        "sec_code,edinet_code,filer_name,listing,fiscal_month,industry\n"
        "72030,E02144,トヨタ自動車株式会社,上場,3月31日,輸送用機器\n",
        encoding="utf-8",
    )
    secret = tmp_path / "secret.json"
    secret.write_text('{"edinet": {"api_key": "TESTKEY"}}', encoding="utf-8")

    monkeypatch.setattr(paths, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(paths, "DOCUMENTS_DIR", tmp_path / "documents")
    monkeypatch.setattr(paths, "XBRL_DIR", tmp_path / "xbrl")
    monkeypatch.setattr(paths, "DERIVED_DIR", tmp_path / "derived")
    monkeypatch.setattr(paths, "PRICES_DIR", tmp_path / "prices")
    monkeypatch.setattr(paths, "MAPPINGS_DIR", tmp_path / "mappings")
    monkeypatch.setattr(paths, "SPLIT_ADJUST_DIR", tmp_path / "split_adjust")
    monkeypatch.setattr(paths, "COMPANY_MAP", company_map)
    monkeypatch.setattr(paths, "SECRET_PATH", secret)

    out_dir = tmp_path / "cwd"
    out_dir.mkdir()
    monkeypatch.setattr(paths, "output_dir", lambda: out_dir)

    # company_map and config modules cached the path at import time — refresh.
    from scripts import company_map as cm_module
    monkeypatch.setattr(cm_module.paths, "COMPANY_MAP", company_map)
    monkeypatch.setattr(config, "SECRET_PATH", secret)

    # json_export rebuilds output paths from paths.output_dir() at call time
    # via paths module attribute, so the monkeypatch above is enough.
    return out_dir


def _seed_documents(tmp_path: Path, sec_code: str = "7203", *, fill_window: bool = True) -> str:
    """Drop one documents/{date}.json with a single 7203 annual report row.

    When ``fill_window`` is True (default), the function also seeds empty
    documents JSONs for every other weekday in the FY2024 submission window
    so that find_missing_windows() reports zero gaps and the pipeline
    proceeds to analysis. Set fill_window=False to specifically test the
    needs_bootstrap path.

    Returns the doc_id used so the test can assert against the same value.
    """
    from scripts.doc_list import build_expected_windows

    # Submission date for Toyota FY2024 was 2025-06-18 (verified from real cache).
    payload_with_filing = {
        "metadata": {"status": "200"},
        "results": [{
            "edinetCode": "E02144",
            "docID": "S100VWVY",
            "docTypeCode": "120",
            "filerName": "トヨタ自動車株式会社",
            "periodStart": "2024-04-01",
            "periodEnd": "2025-03-31",
            "submitDateTime": "2025-06-18 09:00",
            "xbrlFlag": "1",
        }],
    }
    (tmp_path / "documents" / "2025-06-18.json").write_text(
        json.dumps(payload_with_filing), encoding="utf-8"
    )

    if fill_window:
        # Seed empty payloads for the rest of the expected window so that the
        # gap detector is satisfied. years=1 keeps the seed count small.
        for d in build_expected_windows("7203", years=1):
            target = tmp_path / "documents" / f"{d.isoformat()}.json"
            if not target.exists():
                target.write_text(
                    json.dumps({"metadata": {"status": "200"}, "results": []}),
                    encoding="utf-8",
                )
    return "S100VWVY"


def _stub_xbrl_download(monkeypatch) -> None:
    """Make download_xbrl_zip return the bundled fixture instead of fetching."""
    def fake_download(api_key, doc_id, **kwargs):
        if doc_id != "S100VWVY":
            raise AssertionError(f"unexpected doc_id {doc_id} in offline test")
        return TOYOTA_FIXTURE
    # xbrl_extract.download_xbrl_zip is imported by timeseries (via fetch_and_extract)
    # and split_adjust both — replace it at the source module.
    monkeypatch.setattr(xbrl_extract, "download_xbrl_zip", fake_download)
    monkeypatch.setattr(split_adjust, "download_xbrl_zip", fake_download)


def _stub_yfinance(monkeypatch) -> None:
    """Bypass network: return a deterministic 5-day Close series."""
    idx = pd.to_datetime(["2025-03-25", "2025-03-26", "2025-03-27", "2025-03-28", "2025-03-31"])
    history = pd.DataFrame(
        {"Close": [2500.0, 2550.0, 2580.0, 2600.0, 2616.0]},
        index=idx,
    )
    monkeypatch.setattr(
        stock_price, "fetch_history",
        lambda sec_code, **kw: history,
    )


def _run_analyze(argv: list[str]) -> tuple[int, dict]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = pipeline.main(argv)
    return rc, json.loads(buf.getvalue())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_analyze_end_to_end_with_fixture(monkeypatch, tmp_path) -> None:
    out_dir = _stub_paths(monkeypatch, tmp_path)
    _seed_documents(tmp_path)
    _stub_xbrl_download(monkeypatch)
    _stub_yfinance(monkeypatch)

    rc, body = _run_analyze(["analyze", "--sec-code", "7203", "--years", "1"])

    assert rc == 0, body
    assert body["status"] == "success"
    assert body["outputs"]["html"].endswith("report_7203.html")
    assert body["outputs"]["data_json"]["7203"].endswith("data_7203.json")
    # Both artifacts land in CWD (= out_dir).
    assert (out_dir / "report_7203.html").exists()
    assert (out_dir / "data_7203.json").exists()


def test_analyze_split_adjust_cache_persisted(monkeypatch, tmp_path) -> None:
    _stub_paths(monkeypatch, tmp_path)
    _seed_documents(tmp_path)
    _stub_xbrl_download(monkeypatch)
    _stub_yfinance(monkeypatch)

    rc, _ = _run_analyze(["analyze", "--sec-code", "7203", "--years", "1"])
    assert rc == 0

    sa_path = tmp_path / "split_adjust" / "7203.json"
    assert sa_path.exists()
    sa = json.loads(sa_path.read_text())
    assert sa["source_doc_id"] == "S100VWVY"
    # The latest restated EPS equals the raw EPS for Toyota FY2024 (no split).
    assert sa["restated_eps"]["2025-03-31"] == pytest.approx(359.56)


def test_analyze_needs_bootstrap_when_documents_missing(monkeypatch, tmp_path) -> None:
    """No documents/*.json at all -> DocumentsNotBootstrappedError -> needs_bootstrap.

    The error message includes the bootstrap command verbatim, so we look
    for the ${CLAUDE_SKILL_DIR} marker in the top-level reason field rather
    than in a structured per_code entry (that variant is exercised by the
    "incomplete window" path test below).
    """
    _stub_paths(monkeypatch, tmp_path)
    # Intentionally do NOT seed documents.
    _stub_yfinance(monkeypatch)
    rc, body = _run_analyze(["analyze", "--sec-code", "7203", "--years", "1"])

    assert rc != 0
    assert body["status"] == "needs_bootstrap"
    assert "${CLAUDE_SKILL_DIR}" in body["reason"]


def test_analyze_needs_bootstrap_when_window_has_holes(monkeypatch, tmp_path) -> None:
    """One filing present, but the expected submission window has holes."""
    _stub_paths(monkeypatch, tmp_path)
    _seed_documents(tmp_path, fill_window=False)  # only the filing day, not the window
    _stub_yfinance(monkeypatch)
    rc, body = _run_analyze(["analyze", "--sec-code", "7203", "--years", "1"])

    assert rc != 0
    assert body["status"] == "needs_bootstrap"
    assert body["per_code"][0]["status"] == "needs_bootstrap"
    assert body["per_code"][0]["missing_weekday_count"] > 0
    assert "${CLAUDE_SKILL_DIR}" in body["per_code"][0]["suggested_command"]


def test_analyze_config_error_when_secret_missing(monkeypatch, tmp_path) -> None:
    _stub_paths(monkeypatch, tmp_path)
    paths.SECRET_PATH.unlink()
    _seed_documents(tmp_path)

    rc, body = _run_analyze(["analyze", "--sec-code", "7203", "--years", "1"])

    assert rc != 0
    assert body["status"] == "config_error"
    assert "secret.json" in body["reason"]


def test_analyze_unknown_sec_code(monkeypatch, tmp_path) -> None:
    _stub_paths(monkeypatch, tmp_path)
    _seed_documents(tmp_path)

    rc, body = _run_analyze(["analyze", "--sec-code", "9999", "--years", "1"])

    assert rc != 0
    assert body["status"] == "error"
    assert "9999" in body["reason"]


def test_analyze_does_not_reescalate_mapped_items(monkeypatch, tmp_path) -> None:
    """BUG-005: items with an explicit mapping entry must not re-trigger
    needs_mapping, even if some periods fail to resolve them."""
    from scripts import mapping_resolver, timeseries

    _stub_paths(monkeypatch, tmp_path)
    _seed_documents(tmp_path)
    _stub_xbrl_download(monkeypatch)
    _stub_yfinance(monkeypatch)

    # Seed a mapping cache claiming SharesOutstanding is mapped (even though
    # the stub timeseries below will still report it as unresolved). The
    # pipeline must NOT escalate because the user has already provided an
    # explicit mapping entry.
    mapping_resolver.save_mapping("7203", {
        "mappings": {
            "SharesOutstanding": {
                "element": "jpcrp_cor:Whatever",
                "context": "FilingDateInstant",
                "rationale": "test",
            },
        },
        "unresolved": [],
    })

    # Force build_timeseries to claim SharesOutstanding is unresolved (the
    # real fixture resolves it, so we need a stub for this test).
    real_build = timeseries.build_timeseries

    def fake_build(sec_code, api_key, **kw):
        df, _unresolved, nan_periods = real_build(sec_code, api_key, **kw)
        return df, ["SharesOutstanding"], nan_periods

    monkeypatch.setattr("scripts.pipeline.build_timeseries", fake_build)

    rc, body = _run_analyze(["analyze", "--sec-code", "7203", "--years", "1"])
    assert rc == 0, body
    assert body["status"] == "success", body


def test_analyze_warns_when_mapped_item_nan_for_some_periods(monkeypatch, tmp_path) -> None:
    """BUG-006: when an item has a mapping entry but resolves to None in some
    periods (taxonomy drift), a per-period warning should appear so the user
    can tell that case apart from blanket mapping failure (BUG-002 class)."""
    from scripts import mapping_resolver, timeseries

    _stub_paths(monkeypatch, tmp_path)
    _seed_documents(tmp_path)
    _stub_xbrl_download(monkeypatch)
    _stub_yfinance(monkeypatch)

    # Mapping cache: SharesOutstanding is declared as mapped.
    mapping_resolver.save_mapping("7203", {
        "mappings": {
            "SharesOutstanding": {
                "element": "jpcrp_cor:Whatever",
                "context": "FilingDateInstant",
                "rationale": "test",
            },
        },
        "unresolved": [],
    })

    # Force build_timeseries to return rows where SharesOutstanding is None.
    real_build = timeseries.build_timeseries

    def fake_build(sec_code, api_key, *, tracked_keys=None, **kw):
        df, _u, _n = real_build(
            sec_code, api_key, tracked_keys=tracked_keys, **kw
        )
        df["SharesOutstanding"] = None
        # Simulate that all rows are NaN for SharesOutstanding.
        nan_periods = {"SharesOutstanding": [str(p) for p in df.index]}
        return df, [], nan_periods

    monkeypatch.setattr("scripts.pipeline.build_timeseries", fake_build)

    rc, body = _run_analyze(["analyze", "--sec-code", "7203", "--years", "1"])
    assert rc == 0, body
    warnings = body["warnings"]
    matching = [w for w in warnings if "SharesOutstanding is NaN" in w]
    assert matching, f"expected per-period NaN warning, got {warnings}"
    assert "taxonomy may have changed" in matching[0]


def test_analyze_refuses_output_dir_inside_skill_root(monkeypatch, tmp_path) -> None:
    """BUG-001 防御: --output-dir が SKILL_ROOT 配下なら error で停止する。"""
    _stub_paths(monkeypatch, tmp_path)
    _seed_documents(tmp_path)
    # Pick an arbitrary subdir under the real SKILL_ROOT (any path works since
    # the sanity check resolves before mkdir-ing files).
    bad_dir = paths.SKILL_ROOT / "cache"
    rc, body = _run_analyze([
        "analyze", "--sec-code", "7203", "--years", "1",
        "--output-dir", str(bad_dir),
    ])
    assert rc != 0
    assert body["status"] == "error"
    assert "Skill directory" in body["reason"]


def test_analyze_force_refresh_clears_per_sec_caches_before_run(monkeypatch, tmp_path) -> None:
    out_dir = _stub_paths(monkeypatch, tmp_path)
    _seed_documents(tmp_path)
    _stub_xbrl_download(monkeypatch)
    _stub_yfinance(monkeypatch)

    # First run to populate derived caches.
    rc1, _ = _run_analyze(["analyze", "--sec-code", "7203", "--years", "1"])
    assert rc1 == 0
    timeseries_csv = tmp_path / "derived" / "timeseries_7203.csv"
    first_mtime = timeseries_csv.stat().st_mtime

    # Second run with --force-refresh must rewrite the derived files.
    import time
    time.sleep(0.05)  # ensure mtime resolution can distinguish
    rc2, _ = _run_analyze(["analyze", "--sec-code", "7203", "--years", "1", "--force-refresh"])
    assert rc2 == 0
    second_mtime = timeseries_csv.stat().st_mtime
    assert second_mtime > first_mtime

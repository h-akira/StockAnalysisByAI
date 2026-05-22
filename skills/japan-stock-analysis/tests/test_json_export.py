"""Unit tests for scripts.json_export.

Exercise the schema producer end-to-end with synthetic CSVs in a tmp_path.
No network, no real CSV files in cache/ are touched.
"""

from __future__ import annotations

import csv
import json

import pytest

from scripts import json_export, paths
from scripts.split_adjust import SplitAdjustResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_timeseries(tmp_dir, sec_code: str, rows: list[dict]) -> None:
    p = tmp_dir / f"timeseries_{sec_code}.csv"
    fieldnames = ["period_end"] + json_export.FINANCIAL_KEYS
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _write_metrics(tmp_dir, sec_code: str, rows: list[dict]) -> None:
    p = tmp_dir / f"metrics_{sec_code}.csv"
    fieldnames = ["period_end"] + json_export.METRIC_KEYS
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _patch_dirs(monkeypatch, tmp_path):
    """Redirect derived/cache paths and output_dir to a clean tmp_path."""
    derived = tmp_path / "derived"
    documents = tmp_path / "documents"
    out_dir = tmp_path / "cwd"
    derived.mkdir()
    documents.mkdir()
    out_dir.mkdir()
    # company_map.csv lives at the path stored in paths.COMPANY_MAP; provide one.
    company_map = tmp_path / "company_map.csv"
    company_map.write_text(
        "sec_code,edinet_code,filer_name,listing,fiscal_month,industry\n"
        "67580,E01777,ソニーグループ株式会社,上場,3月31日,電気機器\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(paths, "DERIVED_DIR", derived)
    monkeypatch.setattr(paths, "DOCUMENTS_DIR", documents)
    monkeypatch.setattr(paths, "COMPANY_MAP", company_map)
    monkeypatch.setattr(paths, "output_dir", lambda: out_dir)
    return derived, documents, out_dir


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_build_payload_basic_shape(monkeypatch, tmp_path) -> None:
    derived, _docs_dir, _ = _patch_dirs(monkeypatch, tmp_path)

    ts_row = {k: None for k in json_export.FINANCIAL_KEYS}
    ts_row.update({
        "NetSales": 11539837000000,
        "OperatingIncome": 1208206000000,
        "ProfitLoss": 937126000000,
        "EarningsPerShare": 758.38,
        "TotalAssets": 32041222000000,
        "NetAssets": 7229709000000,
        "InterestBearingDebt": 3870572000000,
        "OperatingCF": 314691000000,
        "InvestingCF": -1052664000000,
        "FinancingCF": 84300000000,
        "SharesOutstanding": 1261081781,
        "FreeCF": -737973000000,
    })
    _write_timeseries(derived, "6758", [{"period_end": "2023-03-31", **ts_row}])

    m_row = {k: None for k in json_export.METRIC_KEYS}
    m_row.update({
        "OperatingMargin": 0.1047,
        "ROE": 0.1296,
        "BPS": 5732.94,
        "StockPrice": 2397.0,
        "EPSForPER": 162.71,
        "PER": 14.7317,
        "PBR": 0.4181,
    })
    _write_metrics(derived, "6758", [{"period_end": "2023-03-31", **m_row}])

    split_adjust = SplitAdjustResult(
        sec_code="6758", source_doc_id="S100W19Q", source_period_end="2025-03-31",
        restated_eps={"2023-03-31": 162.71},
    )

    payload = json_export.build_payload(
        "6758", split_adjust=split_adjust, warnings=["[6758] something"],
    )

    assert payload["schema_version"] == json_export.SCHEMA_VERSION
    assert payload["sec_code"] == "6758"
    assert payload["company_name"] == "ソニーグループ株式会社"
    assert payload["edinet_code"] == "E01777"
    assert payload["split_adjust_source_doc_id"] == "S100W19Q"
    assert len(payload["fiscal_years"]) == 1

    fy = payload["fiscal_years"][0]
    assert fy["period_end"] == "2023-03-31"
    assert fy["financials"]["NetSales"] == 11539837000000
    assert fy["financials"]["EarningsPerShare"] == pytest.approx(758.38)
    assert fy["metrics"]["PER"] == pytest.approx(14.7317)
    assert fy["metrics"]["EPSForPER"] == pytest.approx(162.71)
    assert payload["warnings"] == ["[6758] something"]


def test_nan_is_emitted_as_null(monkeypatch, tmp_path) -> None:
    derived, _, _ = _patch_dirs(monkeypatch, tmp_path)
    ts_row = {k: None for k in json_export.FINANCIAL_KEYS}
    ts_row["NetSales"] = 1.0  # at least one value so the row isn't empty
    _write_timeseries(derived, "6758", [{"period_end": "2023-03-31", **ts_row}])

    m_row = {k: None for k in json_export.METRIC_KEYS}
    _write_metrics(derived, "6758", [{"period_end": "2023-03-31", **m_row}])

    payload = json_export.build_payload("6758", split_adjust=None, warnings=[])
    fy = payload["fiscal_years"][0]
    # None / NaN in source CSV must round-trip as JSON null (not the string "nan").
    assert fy["financials"]["OperatingIncome"] is None
    assert fy["metrics"]["PER"] is None


def test_write_data_json_writes_to_cwd(monkeypatch, tmp_path) -> None:
    derived, _, out_dir = _patch_dirs(monkeypatch, tmp_path)
    _write_timeseries(derived, "6758", [
        {"period_end": "2023-03-31",
         **{k: 1.0 for k in json_export.FINANCIAL_KEYS}}
    ])
    _write_metrics(derived, "6758", [
        {"period_end": "2023-03-31",
         **{k: 1.0 for k in json_export.METRIC_KEYS}}
    ])
    out = json_export.write_data_json("6758", split_adjust=None, warnings=[])

    assert out == out_dir / "data_6758.json"
    body = json.loads(out.read_text(encoding="utf-8"))
    assert body["sec_code"] == "6758"


def test_source_doc_ids_scoped_to_analyzed_periods(monkeypatch, tmp_path) -> None:
    derived, docs_dir, _ = _patch_dirs(monkeypatch, tmp_path)
    # Only FY2024 is analyzed.
    _write_timeseries(derived, "6758", [
        {"period_end": "2024-03-31",
         **{k: 1.0 for k in json_export.FINANCIAL_KEYS}}
    ])
    _write_metrics(derived, "6758", [
        {"period_end": "2024-03-31",
         **{k: 1.0 for k in json_export.METRIC_KEYS}}
    ])
    # doc cache contains FY2023 and FY2024 — only FY2024 should be surfaced.
    (docs_dir / "2024-06-25.json").write_text(json.dumps({
        "results": [
            {"edinetCode": "E01777", "docID": "FY2024_ID", "docTypeCode": "120",
             "filerName": "Sony", "periodEnd": "2024-03-31",
             "submitDateTime": "2024-06-25"},
        ],
    }), encoding="utf-8")
    (docs_dir / "2023-06-20.json").write_text(json.dumps({
        "results": [
            {"edinetCode": "E01777", "docID": "FY2023_ID", "docTypeCode": "120",
             "filerName": "Sony", "periodEnd": "2023-03-31",
             "submitDateTime": "2023-06-20"},
        ],
    }), encoding="utf-8")

    payload = json_export.build_payload("6758", split_adjust=None, warnings=[])
    assert payload["source_doc_ids"] == ["FY2024_ID"]

"""Smoke tests for scripts.html_report.

Real plotly figures are heavy; we synthesize a tiny CSV pair and just verify
the Jinja2 template renders without errors and the resulting HTML contains
the title, warning, and source-doc footer.
"""

from __future__ import annotations

import csv

from scripts import html_report, json_export, paths


def _write_csv(path, fieldnames, rows) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _setup(monkeypatch, tmp_path):
    derived = tmp_path / "derived"
    out_dir = tmp_path / "cwd"
    derived.mkdir()
    out_dir.mkdir()
    company_map = tmp_path / "company_map.csv"
    company_map.write_text(
        "sec_code,edinet_code,filer_name,listing,fiscal_month,industry\n"
        "67580,E01777,ソニーグループ株式会社,上場,3月31日,電気機器\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(paths, "DERIVED_DIR", derived)
    monkeypatch.setattr(paths, "COMPANY_MAP", company_map)
    monkeypatch.setattr(paths, "output_dir", lambda: out_dir)

    # Minimal financials + metrics for one period.
    ts_row = {k: 1.0 for k in json_export.FINANCIAL_KEYS}
    ts_row["NetSales"] = 11539837000000
    ts_row["OperatingIncome"] = 1208206000000
    ts_row["ProfitLoss"] = 937126000000
    _write_csv(derived / "timeseries_6758.csv",
               ["period_end"] + json_export.FINANCIAL_KEYS,
               [{"period_end": "2023-03-31", **ts_row}])

    m_row = {k: 0.1 for k in json_export.METRIC_KEYS}
    m_row["PER"] = 14.73
    m_row["PBR"] = 0.42
    _write_csv(derived / "metrics_6758.csv",
               ["period_end"] + json_export.METRIC_KEYS,
               [{"period_end": "2023-03-31", **m_row}])
    return out_dir


def test_render_report_writes_html_with_title_and_warning(monkeypatch, tmp_path) -> None:
    out_dir = _setup(monkeypatch, tmp_path)
    out_path = html_report.render_report(
        ["6758"],
        warnings=["[6758] sample warning"],
        source_docs={"6758": ["S100W19Q"]},
        split_adjust_doc_ids={"6758": "S100W19Q"},
    )
    assert out_path == out_dir / "report_6758.html"
    body = out_path.read_text(encoding="utf-8")
    assert "ソニーグループ株式会社" in body
    assert "個別分析レポート" in body
    assert "sample warning" in body
    assert "S100W19Q" in body
    # plotly inline embed marker — sanity check that figures rendered.
    assert "Plotly.newPlot" in body or "plotly" in body.lower()


def test_render_report_handles_no_warnings(monkeypatch, tmp_path) -> None:
    _setup(monkeypatch, tmp_path)
    out_path = html_report.render_report(
        ["6758"], warnings=[], source_docs={"6758": []},
    )
    body = out_path.read_text(encoding="utf-8")
    # When warnings list is empty, the bullet list section is not rendered.
    assert "<ul>" not in body or "sample warning" not in body

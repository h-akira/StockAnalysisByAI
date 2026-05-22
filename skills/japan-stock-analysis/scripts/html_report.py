"""HTML report renderer.

Plotly figures are still built in Python; the surrounding layout (header,
metadata, warnings, footer) is rendered via Jinja2 from
templates/report_template.html.j2 so the design can iterate without
touching the figure-construction code.

The data the figures plot is the *same* CSV that json_export emits the
JSON copy of — both come from cache/derived/*.csv. Edit timeseries.py or
metrics.py to change the numbers; this module only chooses what to plot.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from jinja2 import Environment, FileSystemLoader, select_autoescape
from plotly.subplots import make_subplots

from scripts import paths
from scripts.company_map import lookup as lookup_company
from scripts.json_export import SCHEMA_VERSION
from scripts.metrics import metrics_csv_path
from scripts.split_adjust import SplitAdjustResult
from scripts.timeseries import timeseries_csv_path

TRILLION = 1e12

TEMPLATE_NAME = "report_template.html.j2"


def _company_name(sec_code: str) -> str:
    rec = lookup_company(sec_code)
    return rec["filer_name"] if rec else sec_code


def _load_joined(sec_code: str) -> pd.DataFrame:
    ts = pd.read_csv(timeseries_csv_path(sec_code), parse_dates=["period_end"])
    mt = pd.read_csv(metrics_csv_path(sec_code), parse_dates=["period_end"])
    return ts.merge(mt, on="period_end", how="left").set_index("period_end").sort_index()


def _fiscal_labels(df: pd.DataFrame) -> list[str]:
    """X-axis label like 'FY2024' from period_end.

    Limitation: period_end month <= 6 -> year - 1, otherwise year. Mislabels
    fiscal years ending in months 4-6 by one year (carried from step6).
    """
    labels: list[str] = []
    for pe in df.index:
        fy = pe.year - 1 if pe.month <= 6 else pe.year
        labels.append(f"FY{fy}")
    return labels


def build_single(df: pd.DataFrame, name: str, sec_code: str) -> go.Figure:
    x = _fiscal_labels(df)
    fig = make_subplots(
        rows=4, cols=1,
        subplot_titles=(
            "売上高（兆円）",
            "営業利益・当期純利益（兆円）",
            "ROE・自己資本比率・営業利益率（%）",
            "PER・PBR（倍）",
        ),
        vertical_spacing=0.08,
    )
    fig.add_bar(x=x, y=df["NetSales"] / TRILLION, name="売上高", row=1, col=1)
    for col, label in [("OperatingIncome", "営業利益"), ("ProfitLoss", "当期純利益")]:
        fig.add_bar(x=x, y=df[col] / TRILLION, name=label, row=2, col=1)
    for col, label in [("ROE", "ROE"), ("EquityRatio", "自己資本比率"), ("OperatingMargin", "営業利益率")]:
        fig.add_scatter(x=x, y=df[col] * 100, name=label, mode="lines+markers", row=3, col=1)
    for col, label in [("PER", "PER"), ("PBR", "PBR")]:
        fig.add_scatter(x=x, y=df[col], name=label, mode="lines+markers", row=4, col=1)
    fig.update_layout(
        title=f"{name}（{sec_code}）財務・指標推移",
        height=1400, barmode="group", hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=-0.05),
    )
    return fig


def build_comparison(frames: dict[str, pd.DataFrame], names: dict[str, str]) -> go.Figure:
    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=("売上高（兆円）", "ROE（%）", "営業利益率（%）", "PER（倍）"),
        vertical_spacing=0.12, horizontal_spacing=0.08,
    )
    spec = [
        (1, 1, "NetSales", "trillion"),
        (1, 2, "ROE", "percent"),
        (2, 1, "OperatingMargin", "percent"),
        (2, 2, "PER", "raw"),
    ]
    for sec_code, df in frames.items():
        x = _fiscal_labels(df)
        for row, col, field, kind in spec:
            if kind == "trillion":
                y = df[field] / TRILLION
            elif kind == "percent":
                y = df[field] * 100
            else:
                y = df[field]
            fig.add_scatter(
                x=x, y=y, name=names[sec_code], mode="lines+markers",
                legendgroup=sec_code, showlegend=(row == 1 and col == 1),
                row=row, col=col,
            )
    fig.update_layout(
        title="比較ビュー",
        height=850, hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=-0.08),
    )
    return fig


def _render_figures(figs: list[go.Figure]) -> list[dict]:
    """Return Jinja-friendly dicts with the figure HTML embedded. The first
    figure embeds plotly.js inline; subsequent ones reuse it."""
    parts = []
    for i, fig in enumerate(figs):
        include = "inline" if i == 0 else False
        parts.append({"html": pio.to_html(fig, full_html=False, include_plotlyjs=include)})
    return parts


def _render_template(context: dict) -> str:
    env = Environment(
        loader=FileSystemLoader(str(paths.TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "j2"]),
    )
    tpl = env.get_template(TEMPLATE_NAME)
    return tpl.render(**context)


def render_report(
    sec_codes: list[str],
    *,
    warnings: list[str] | None = None,
    source_docs: dict[str, list[str]] | None = None,
    split_adjust_doc_ids: dict[str, str] | None = None,
) -> Path:
    """Render an HTML report for 1+ securities codes. Writes to paths.output_dir().

    ``source_docs`` and ``split_adjust_doc_ids`` are surfaced in the report
    footer so the reader can trace back to the underlying EDINET filings.
    Both are optional; missing entries simply omit that footer line.
    """
    if not sec_codes:
        raise ValueError("sec_codes must contain at least one code")

    frames = {c: _load_joined(c) for c in sec_codes}
    names = {c: _company_name(c) for c in sec_codes}

    figs: list[go.Figure] = []
    for c in sec_codes:
        figs.append(build_single(frames[c], names[c], c))
    if len(sec_codes) >= 2:
        figs.append(build_comparison(frames, names))
        out_name = f"report_{'_'.join(sec_codes)}.html"
        title = "個別分析レポート: " + " vs ".join(names[c] for c in sec_codes)
    else:
        out_name = f"report_{sec_codes[0]}.html"
        title = f"個別分析レポート: {names[sec_codes[0]]}"

    context = {
        "title": title,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "schema_version": SCHEMA_VERSION,
        "warnings": warnings or [],
        "figures": _render_figures(figs),
        "source_docs": source_docs or {c: [] for c in sec_codes},
        "split_adjust_doc_ids": split_adjust_doc_ids or {},
    }

    out_path = paths.output_dir() / out_name
    out_path.write_text(_render_template(context), encoding="utf-8")
    return out_path

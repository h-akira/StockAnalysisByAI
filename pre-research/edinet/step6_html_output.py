"""
Step 6: Render financial / valuation time series to a standalone HTML report.

== What this script verifies ==
Whether the Step 4/5 outputs can be turned into an interactive, standalone
HTML file (openable in a browser with no server, no internet) using plotly.

== Inputs ==
  data/timeseries_{sec_code}.csv : EDINET financials (from step4)
  data/metrics_{sec_code}.csv    : computed metrics (from step5)

== Output ==
  data/report_{sec_code}.html              (single company)
  data/report_{code1}_{code2}.html         (comparison; codes joined by '_')

== Modes ==
  Single company  : python step6_html_output.py --sec-code 7203
  Comparison view : python step6_html_output.py --sec-code 7203 6758

  Single mode renders (sales and profits are on separate rows because sales
  is ~10x the profit figures and would otherwise flatten profit movement):
    - Sales                                  (bar, own axis)
    - Operating income / Net income          (grouped bar, own axis)
    - ROE / EquityRatio / OperatingMargin    (line)
    - PER / PBR                              (line)
  Comparison mode additionally overlays both companies on shared axes for
  the headline metrics so they can be compared directly.

== Standalone-ness ==
plotly.io.to_html(..., include_plotlyjs="inline") embeds plotly.js into the
HTML so the file works offline. This is the property we want to verify.

== Stock-split caveat (carried from Step 5) ==
PER/PBR for periods before a stock split can be distorted because EDINET EPS
is filing-time-based while yfinance prices are adjusted to the latest split.
The chart annotates this rather than silently plotting misleading values.
See verification_results.md Step 5 for the full explanation.

== Pass criterion ==
A standalone HTML opens in a browser and shows the financial and metric
charts; comparison mode shows both companies overlaid.

Usage:
  python step6_html_output.py --sec-code 7203
  python step6_html_output.py --sec-code 7203 6758
"""

import argparse
import csv
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from plotly.subplots import make_subplots

DATA_DIR = Path(__file__).parent / "data"
COMPANY_MAP_CSV = DATA_DIR / "company_map.csv"

# JPY values are stored in yen; dividing by 1e12 gives 兆円 (trillion yen),
# the natural scale for large-cap financials.
TRILLION = 1e12


def company_name(sec_code: str) -> str:
    """Resolve a display name from company_map.csv (5-digit padded code)."""
    padded = (sec_code + "0") if (len(sec_code) == 4 and sec_code.isdigit()) else sec_code
    with COMPANY_MAP_CSV.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["sec_code"] == padded:
                return row["filer_name"]
    return sec_code


def load(sec_code: str) -> pd.DataFrame:
    """Join timeseries + metrics on period_end for one company."""
    ts = pd.read_csv(DATA_DIR / f"timeseries_{sec_code}.csv", parse_dates=["period_end"])
    mt = pd.read_csv(DATA_DIR / f"metrics_{sec_code}.csv", parse_dates=["period_end"])
    df = ts.merge(mt, on="period_end", how="left").set_index("period_end").sort_index()
    return df


def fiscal_labels(df: pd.DataFrame) -> list[str]:
    """X-axis labels like 'FY2024' from period_end (2025-03-31 -> FY2024).

    Rule actually applied: if period_end month <= 6, fiscal year = year - 1;
    otherwise fiscal year = year. This correctly handles the common cases:
      - 3月決算 (period_end 2025-03-31, month=3<=6)  -> FY2024
      - 12月決算 (period_end 2024-12-31, month=12>6) -> FY2024
    LIMITATION: a fiscal year-end in months 4-6 (e.g. May/June year-end)
    would be mislabeled by one year. The verification set is March-end only,
    so this is acceptable here; the production implementation should derive
    the label from the actual fiscal-month, not approximate from period_end.
    """
    labels = []
    for pe in df.index:
        fy = pe.year - 1 if pe.month <= 6 else pe.year
        labels.append(f"FY{fy}")
    return labels


def build_single(df: pd.DataFrame, name: str, sec_code: str) -> go.Figure:
    x = fiscal_labels(df)
    # Sales and profits are split into separate rows on purpose: sales is ~10x
    # the profit figures, so plotting them on one shared axis squashes the
    # year-over-year movement of operating/net income into a flat line.
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

    # Row 1: sales only (its own axis so the scale isn't dominated downstream).
    fig.add_bar(x=x, y=df["NetSales"] / TRILLION, name="売上高", row=1, col=1)

    # Row 2: profit bars share an axis whose range matches their own scale.
    for col, label in [("OperatingIncome", "営業利益"),
                       ("ProfitLoss", "当期純利益")]:
        fig.add_bar(x=x, y=df[col] / TRILLION, name=label, row=2, col=1)

    # Row 3: ratios as percentages.
    for col, label in [("ROE", "ROE"),
                       ("EquityRatio", "自己資本比率"),
                       ("OperatingMargin", "営業利益率")]:
        fig.add_scatter(x=x, y=df[col] * 100, name=label, mode="lines+markers",
                        row=3, col=1)

    # Row 4: valuation multiples.
    for col, label in [("PER", "PER"), ("PBR", "PBR")]:
        fig.add_scatter(x=x, y=df[col], name=label, mode="lines+markers",
                        row=4, col=1)

    fig.update_layout(
        title=f"{name}（{sec_code}）財務・指標推移",
        height=1400, barmode="group", hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=-0.05),
    )
    return fig


def build_comparison(frames: dict[str, pd.DataFrame], names: dict[str, str]) -> go.Figure:
    """Overlay headline metrics for multiple companies on shared axes."""
    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=("売上高（兆円）", "ROE（%）", "営業利益率（%）", "PER（倍）"),
        vertical_spacing=0.12, horizontal_spacing=0.08,
    )
    spec = [
        (1, 1, "NetSales", TRILLION),
        (1, 2, "ROE", 1 / 100),       # value*100 -> divide by (1/100) i.e. *100
        (2, 1, "OperatingMargin", 1 / 100),
        (2, 2, "PER", 1),
    ]
    for sec_code, df in frames.items():
        x = fiscal_labels(df)
        for row, col, field, scale in spec:
            y = df[field] / scale if field == "NetSales" else (
                df[field] * 100 if scale == 1 / 100 else df[field]
            )
            fig.add_scatter(
                x=x, y=y, name=f"{names[sec_code]}",
                mode="lines+markers", legendgroup=sec_code,
                showlegend=(row == 1 and col == 1),
                row=row, col=col,
            )
    fig.update_layout(
        title="二社比較ビュー",
        height=850, hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=-0.08),
    )
    return fig


def write_html(figs: list[go.Figure], out_path: Path, title: str) -> None:
    """Concatenate figures into a single standalone HTML file."""
    parts = [
        f"<html><head><meta charset='utf-8'><title>{title}</title></head><body>",
        f"<h1 style='font-family:sans-serif'>{title}</h1>",
        "<p style='font-family:sans-serif;color:#a00'>"
        "注: 株式分割前後の期は PER/PBR が分割比率分ずれる場合があります"
        "（verification_results.md Step 5 参照）。</p>",
    ]
    for i, fig in enumerate(figs):
        # Embed plotly.js only once (first figure); the rest reference it.
        include = "inline" if i == 0 else False
        parts.append(pio.to_html(fig, full_html=False, include_plotlyjs=include))
    parts.append("</body></html>")
    out_path.write_text("\n".join(parts), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sec-code", required=True, nargs="+",
                        help="one or more 4-digit codes (e.g. 7203, or 7203 6758)")
    args = parser.parse_args()

    codes = args.sec_code
    frames = {c: load(c) for c in codes}
    names = {c: company_name(c) for c in codes}

    figs: list[go.Figure] = []
    for c in codes:
        figs.append(build_single(frames[c], names[c], c))

    if len(codes) >= 2:
        figs.append(build_comparison(frames, names))
        out_name = f"report_{'_'.join(codes)}.html"
        title = "EDINET 検証レポート: " + " vs ".join(names[c] for c in codes)
    else:
        out_name = f"report_{codes[0]}.html"
        title = f"EDINET 検証レポート: {names[codes[0]]}"

    out_path = DATA_DIR / out_name
    write_html(figs, out_path, title)
    print(f"Saved -> {out_path}")
    print(f"Open: file://{out_path}")


if __name__ == "__main__":
    main()

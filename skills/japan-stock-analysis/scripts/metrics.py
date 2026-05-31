"""Financial metrics (ROE, PER, PBR, ...).

Successor of pre-research/edinet/step5_metrics.py with Phase P4 stock-split
correction via scripts.split_adjust (method (a) restated EPS — see
pre-research Step 7 for the rationale).

Caveat still in force: PBR uses raw SharesOutstanding from each year's own
report. For periods that straddle a stock split, BPS is therefore on the
filing-time share-count basis while StockPrice is on the latest-split basis.
This is the same class of issue Step 7 resolved for EPS, but
SummaryOfBusinessResults does not expose a restated SharesOutstanding, so a
clean fix requires a separate channel (deferred — see init_plan.md §4.5 row for
split_adjust).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from scripts import paths
from scripts.split_adjust import SplitAdjustResult
from scripts.stock_price import closes_at_or_before, fetch_history
from scripts.timeseries import timeseries_csv_path


def metrics_csv_path(sec_code: str) -> Path:
    return paths.DERIVED_DIR / f"metrics_{sec_code}.csv"


def load_timeseries(sec_code: str) -> pd.DataFrame:
    csv_path = timeseries_csv_path(sec_code)
    if not csv_path.exists():
        raise FileNotFoundError(
            f"{csv_path} not found. Run scripts.timeseries.build_timeseries first."
        )
    df = pd.read_csv(csv_path)
    df["period_end"] = pd.to_datetime(df["period_end"])
    return df.set_index("period_end").sort_index()


# BUG-009: order-of-magnitude gap between reported raw EPS and the EPS implied
# by ProfitLoss / SharesOutstanding flags periods whose raw EPS is on a
# pre-split (or otherwise inconsistent) basis. Kept deliberately conservative
# so it never fires on normal restatement noise or accounting differences:
#   - only periods where SharesOutstanding is present (implied EPS computable),
#   - only profitable periods (ProfitLoss > 0; avoids unstable ratios near 0
#     and negative EPS),
#   - only a >=3x discrepancy (a true digit-level mismatch, not a few %).
# Periods that can't be checked this way (e.g. SharesOutstanding missing in the
# oldest filings) are left to the SKILL.md §7 AI-side consistency check.
_EPS_IMPLIED_GAP_RATIO = 3.0


def eps_consistency_warning(df: pd.DataFrame) -> str | None:
    """Return a warning string if any period's raw EPS is order-of-magnitude
    inconsistent with ProfitLoss / SharesOutstanding, else None. See BUG-009."""
    flagged: list[str] = []
    for pe in df.index:
        eps = df["EarningsPerShare"].get(pe)
        profit = df["ProfitLoss"].get(pe)
        shares = df["SharesOutstanding"].get(pe)
        if eps is None or profit is None or shares is None:
            continue
        if pd.isna(eps) or pd.isna(profit) or pd.isna(shares):
            continue
        if shares <= 0 or profit <= 0 or eps <= 0:
            continue
        implied = profit / shares
        ratio = max(implied / eps, eps / implied)
        if ratio >= _EPS_IMPLIED_GAP_RATIO:
            flagged.append(
                f"{pe.date().isoformat()} (reported EPS {eps:g}, "
                f"implied {implied:.2f} from ProfitLoss/Shares, ~{ratio:.1f}x apart)"
            )
    if not flagged:
        return None
    return (
        "Raw EarningsPerShare is order-of-magnitude inconsistent with "
        "ProfitLoss/SharesOutstanding for: " + "; ".join(flagged) + ". "
        "Likely a pre-stock-split basis carried over from the filing of that year "
        "(the financials EPS series is reported-as-of-filing, not split-adjusted). "
        "PER uses split-adjusted restated EPS and is unaffected; treat the raw EPS "
        "series for these periods with caution. See BUG-009."
    )


def _restated_eps_series(df: pd.DataFrame, split_adjust: SplitAdjustResult | None) -> pd.Series:
    """Return EPS series for PER calc. Falls back to raw EPS where restated is absent."""
    raw = df["EarningsPerShare"]
    if split_adjust is None:
        return raw
    values: list[float] = []
    for pe in df.index:
        rep = split_adjust.get(pe)
        values.append(float(rep) if rep is not None else float("nan"))
    return pd.Series(values, index=df.index, name="RestatedEPS")


def compute_metrics(
    df: pd.DataFrame,
    prices: pd.Series,
    *,
    eps_for_per: pd.Series | None = None,
) -> pd.DataFrame:
    """Combine financials + prices into a metrics DataFrame.

    Ratios are emitted as decimals (0.12 == 12%). Caller decides whether to
    render as percentage in display.

    ``eps_for_per`` lets PER use a split-adjusted EPS series instead of
    df["EarningsPerShare"]. When None, raw EPS is used (pre-P4 behavior).
    """
    m = pd.DataFrame(index=df.index)
    m["OperatingMargin"] = df["OperatingIncome"] / df["NetSales"]
    m["NetMargin"] = df["ProfitLoss"] / df["NetSales"]
    m["ROE"] = df["ProfitLoss"] / df["NetAssets"]
    m["EquityRatio"] = df["NetAssets"] / df["TotalAssets"]
    m["DERatio"] = df["InterestBearingDebt"] / df["NetAssets"]
    m["SalesGrowth"] = df["NetSales"].pct_change()
    m["ProfitGrowth"] = df["ProfitLoss"].pct_change()
    m["BPS"] = df["NetAssets"] / df["SharesOutstanding"]
    m["StockPrice"] = prices.reindex(m.index)
    eps = eps_for_per if eps_for_per is not None else df["EarningsPerShare"]
    m["EPSForPER"] = eps
    m["PER"] = m["StockPrice"] / eps
    m["PBR"] = m["StockPrice"] / m["BPS"]
    return m


def build_metrics(
    sec_code: str,
    *,
    use_yfinance: bool = True,
    split_adjust: SplitAdjustResult | None = None,
) -> tuple[pd.DataFrame, list[str]]:
    """Load timeseries, fetch prices, compute metrics. Returns (df, warnings)."""
    warnings: list[str] = []
    df = load_timeseries(sec_code)

    # BUG-009: flag raw EPS periods that are order-of-magnitude inconsistent
    # with ProfitLoss/Shares (pre-split basis). Independent of yfinance/PER.
    eps_warning = eps_consistency_warning(df)
    if eps_warning:
        warnings.append(eps_warning)

    if use_yfinance:
        try:
            history = fetch_history(sec_code)
            prices = closes_at_or_before(history, df.index)
        except Exception as e:
            warnings.append(f"yfinance failed: {e!r}; valuation metrics will be NaN.")
            prices = pd.Series(index=df.index, dtype=float, name="StockPrice")
    else:
        prices = pd.Series(index=df.index, dtype=float, name="StockPrice")
        warnings.append("yfinance skipped (--no-yfinance); valuation metrics will be NaN.")

    eps_for_per: pd.Series | None = None
    if split_adjust is not None:
        eps_for_per = _restated_eps_series(df, split_adjust)
        # BUG-003: distinguish "restated_eps is entirely empty" from "only some
        # periods fall outside the 5-year window". The former masks BUG-002-class
        # issues (e.g. JGAAP banks where the IFRS element doesn't exist).
        if not split_adjust.restated_eps:
            warnings.append(
                "split_adjust returned no restated EPS at all. PER will be NaN for all periods. "
                "Likely cause: the latest report's XBRL taxonomy lacks every element probed in "
                "EPS_SUMMARY_ELEMENTS (IFRS / JGAAP, Basic / Diluted). See BUG-002 for context."
            )
        else:
            missing = [pe.date().isoformat() for pe in df.index if split_adjust.get(pe) is None]
            if missing:
                warnings.append(
                    "PER is NaN for periods outside the latest report's restated EPS coverage "
                    f"(5-year window): {missing}. PBR also retains the unfixed share-count basis "
                    "(see split_adjust caveat)."
                )

        # ENH-002: surface non-IFRS-Basic fallback usage so the reader knows
        # which EPS variant fed PER. Diluted is ~slightly< Basic so PER will
        # be ~slightly> the "true" Basic PER.
        fallback_tags = sorted({
            tag for tag in split_adjust.eps_source.values() if tag != "ifrs_basic"
        })
        if fallback_tags:
            warnings.append(
                f"split_adjust used non-IFRS-Basic EPS fallback for some periods: {fallback_tags}. "
                "Verify PER values; Diluted variants in particular produce slightly higher PER "
                "than Basic. See data_*.json metrics for the per-period eps_source."
            )
    else:
        warnings.append(
            "Split adjustment is disabled; PER uses raw EPS and may be off "
            "by the stock-split ratio for periods preceding a split."
        )

    return compute_metrics(df, prices, eps_for_per=eps_for_per), warnings


def save_metrics(sec_code: str, df: pd.DataFrame) -> Path:
    paths.ensure_cache_dirs()
    out = metrics_csv_path(sec_code)
    df.to_csv(out)
    return out

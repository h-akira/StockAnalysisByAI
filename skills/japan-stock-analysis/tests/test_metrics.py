"""Unit tests for scripts.metrics.compute_metrics.

The function is pure (DataFrame in, DataFrame out) and easy to nail down
with hand-checked fixtures. The numbers below mirror Toyota FY2024 from
the production cache so failure points back to a real expectation.
"""

from __future__ import annotations

import pandas as pd
import pytest

from scripts.metrics import compute_metrics, eps_consistency_warning

# Toyota FY2024 financials (from cache/derived/timeseries_7203.csv).
TOYOTA_FY2024 = {
    "NetSales": 48036704000000,
    "OperatingIncome": 4795586000000,
    "ProfitLoss": 4765086000000,
    "EarningsPerShare": 359.56,
    "TotalAssets": 93601350000000,
    "NetAssets": 35924826000000,
    "InterestBearingDebt": 38792879000000,
    "OperatingCF": 3696934000000,
    "InvestingCF": -4189736000000,
    "FinancingCF": 197236000000,
    "SharesOutstanding": 15794987460,
    "FreeCF": -492802000000,
}


def _toyota_df():
    return pd.DataFrame([TOYOTA_FY2024], index=pd.to_datetime(["2025-03-31"]))


def _trivial_prev_year(over: dict, multiplier: float = 0.9) -> dict:
    """Build a previous-year row by scaling every financial field."""
    return {k: (v * multiplier if isinstance(v, (int, float)) else v) for k, v in over.items()}


# ---------- Single-year ratios (no pct_change involved) ----------

def test_operating_margin_matches_definition() -> None:
    m = compute_metrics(_toyota_df(), pd.Series([2616.0], index=_toyota_df().index))
    assert m.loc["2025-03-31", "OperatingMargin"] == pytest.approx(
        TOYOTA_FY2024["OperatingIncome"] / TOYOTA_FY2024["NetSales"]
    )


def test_roe_and_equity_ratio() -> None:
    m = compute_metrics(_toyota_df(), pd.Series([2616.0], index=_toyota_df().index))
    assert m.loc["2025-03-31", "ROE"] == pytest.approx(
        TOYOTA_FY2024["ProfitLoss"] / TOYOTA_FY2024["NetAssets"]
    )
    assert m.loc["2025-03-31", "EquityRatio"] == pytest.approx(
        TOYOTA_FY2024["NetAssets"] / TOYOTA_FY2024["TotalAssets"]
    )


def test_de_ratio_matches_definition() -> None:
    m = compute_metrics(_toyota_df(), pd.Series([2616.0], index=_toyota_df().index))
    assert m.loc["2025-03-31", "DERatio"] == pytest.approx(
        TOYOTA_FY2024["InterestBearingDebt"] / TOYOTA_FY2024["NetAssets"]
    )


def test_bps_per_share() -> None:
    m = compute_metrics(_toyota_df(), pd.Series([2616.0], index=_toyota_df().index))
    assert m.loc["2025-03-31", "BPS"] == pytest.approx(
        TOYOTA_FY2024["NetAssets"] / TOYOTA_FY2024["SharesOutstanding"]
    )


# ---------- Valuation (split-adjusted EPS injected) ----------

def test_per_uses_eps_for_per_when_provided() -> None:
    df = _toyota_df()
    prices = pd.Series([2616.0], index=df.index)
    # If a split-adjusted EPS is provided, it should override the raw EPS for PER.
    restated = pd.Series([180.00], index=df.index)
    m = compute_metrics(df, prices, eps_for_per=restated)
    assert m.loc["2025-03-31", "EPSForPER"] == pytest.approx(180.00)
    assert m.loc["2025-03-31", "PER"] == pytest.approx(2616.0 / 180.00)


def test_per_falls_back_to_raw_eps_when_no_override() -> None:
    df = _toyota_df()
    m = compute_metrics(df, pd.Series([2616.0], index=df.index))
    assert m.loc["2025-03-31", "EPSForPER"] == pytest.approx(TOYOTA_FY2024["EarningsPerShare"])
    assert m.loc["2025-03-31", "PER"] == pytest.approx(
        2616.0 / TOYOTA_FY2024["EarningsPerShare"]
    )


def test_pbr_matches_definition() -> None:
    df = _toyota_df()
    m = compute_metrics(df, pd.Series([2616.0], index=df.index))
    bps = TOYOTA_FY2024["NetAssets"] / TOYOTA_FY2024["SharesOutstanding"]
    assert m.loc["2025-03-31", "PBR"] == pytest.approx(2616.0 / bps)


# ---------- pct_change behavior ----------

def test_growth_columns_are_nan_for_first_period() -> None:
    df = _toyota_df()
    m = compute_metrics(df, pd.Series([2616.0], index=df.index))
    assert pd.isna(m.loc["2025-03-31", "SalesGrowth"])
    assert pd.isna(m.loc["2025-03-31", "ProfitGrowth"])


def test_growth_columns_compute_pct_change_for_subsequent_periods() -> None:
    prev = _trivial_prev_year(TOYOTA_FY2024, multiplier=0.8)  # 25% growth target
    df = pd.DataFrame([prev, TOYOTA_FY2024], index=pd.to_datetime(["2024-03-31", "2025-03-31"]))
    prices = pd.Series([2000.0, 2616.0], index=df.index)
    m = compute_metrics(df, prices)
    assert m.loc["2025-03-31", "SalesGrowth"] == pytest.approx(0.25)
    assert m.loc["2025-03-31", "ProfitGrowth"] == pytest.approx(0.25)


# ---------- price alignment ----------

def test_missing_price_propagates_as_nan() -> None:
    df = _toyota_df()
    # Empty prices -> StockPrice NaN -> PER NaN.
    m = compute_metrics(df, pd.Series(dtype=float))
    assert pd.isna(m.loc["2025-03-31", "StockPrice"])
    assert pd.isna(m.loc["2025-03-31", "PER"])
    assert pd.isna(m.loc["2025-03-31", "PBR"])
    # Financial ratios still computed.
    assert not pd.isna(m.loc["2025-03-31", "ROE"])


# ---------- BUG-009: raw EPS consistency check (must not regress per company) ----------

def _eps_df(rows: dict) -> pd.DataFrame:
    """rows: {period_iso: {EarningsPerShare, ProfitLoss, SharesOutstanding}}."""
    idx = pd.to_datetime(list(rows.keys()))
    return pd.DataFrame(list(rows.values()), index=idx)


def test_eps_consistency_flags_order_of_magnitude_gap() -> None:
    # FY2017 Tokyo Gas-like: reported 23.02 but implied ~123 from profit/shares.
    df = _eps_df({
        "2017-03-31": {"EarningsPerShare": 23.02, "ProfitLoss": 54_044_000_000,
                       "SharesOutstanding": 440_000_000},
    })
    w = eps_consistency_warning(df)
    assert w is not None
    assert "2017-03-31" in w
    assert "BUG-009" in w


def test_eps_consistency_silent_on_normal_restatement_noise() -> None:
    # Healthy period: implied EPS ~ reported within a few % — must NOT fire.
    df = _eps_df({
        "2025-03-31": {"EarningsPerShare": 359.56, "ProfitLoss": 4_765_086_000_000,
                       "SharesOutstanding": 13_250_000_000},  # implied ~359.6
    })
    assert eps_consistency_warning(df) is None


def test_eps_consistency_skips_loss_making_periods() -> None:
    # Negative ProfitLoss / EPS: ratio is unstable, must be skipped (no false alarm).
    df = _eps_df({
        "2020-03-31": {"EarningsPerShare": -5.0, "ProfitLoss": -10_000_000_000,
                       "SharesOutstanding": 400_000_000},
    })
    assert eps_consistency_warning(df) is None


def test_eps_consistency_skips_periods_without_shares() -> None:
    # Oldest filings often lack SharesOutstanding -> not computable, skip it.
    # (Those periods are covered by the SKILL.md §7 AI-side check instead.)
    df = _eps_df({
        "2016-03-31": {"EarningsPerShare": 46.68, "ProfitLoss": 112_977_000_000,
                       "SharesOutstanding": float("nan")},
    })
    assert eps_consistency_warning(df) is None

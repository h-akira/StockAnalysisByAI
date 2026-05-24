"""Unit tests for scripts.xbrl_extract.

Two layers:
- Pure merge / fallthrough logic (no I/O).
- Fixture-based end-to-end extraction against real XBRL zips committed
  under tests/fixtures (Toyota S100VWVY, Sony S100W19Q — both FY2024).
  Expected values come from the pre-research verification and from the
  cache/derived CSVs the production pipeline emits.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import xbrl_extract

FIXTURES = Path(__file__).parent / "fixtures"

# Latest fiscal year reports both filed in 2025-06 (period_end 2025-03-31).
TOYOTA_FIXTURE = FIXTURES / "S100VWVY.zip"
TOYOTA_EDINET_CODE = "E02144"
SONY_FIXTURE = FIXTURES / "S100W19Q.zip"
SONY_EDINET_CODE = "E01777"


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


# ---------------------------------------------------------------------------
# Fixture-based end-to-end extraction (Toyota FY2024, Sony FY2024)
# ---------------------------------------------------------------------------

@pytest.fixture
def toyota_result():
    return xbrl_extract.extract_from_zip(TOYOTA_FIXTURE, TOYOTA_EDINET_CODE, "S100VWVY")


@pytest.fixture
def sony_result():
    return xbrl_extract.extract_from_zip(SONY_FIXTURE, SONY_EDINET_CODE, "S100W19Q")


def test_toyota_fy2024_all_items_resolved(toyota_result) -> None:
    """Toyota IFRS — every whitelisted item must have a value."""
    assert toyota_result.unresolved == [], (
        f"Toyota whitelist should cover everything; missing: {toyota_result.unresolved}"
    )


def test_toyota_fy2024_key_values_match_expected(toyota_result) -> None:
    """Sanity-check the 9 key items against the production CSV snapshot."""
    m = toyota_result.merged
    # NetSales 48.0 trillion JPY (verified via real EDINET data).
    assert int(m["NetSales"]["value"]) == 48036704000000
    assert int(m["OperatingIncome"]["value"]) == 4795586000000
    assert int(m["ProfitLoss"]["value"]) == 4765086000000
    assert float(m["EarningsPerShare"]["value"]) == pytest.approx(359.56)
    assert int(m["TotalAssets"]["value"]) == 93601350000000
    assert int(m["NetAssets"]["value"]) == 35924826000000
    # InterestBearingDebt is summed from two jpigp_cor lines for Toyota.
    assert int(m["InterestBearingDebt"]["value"]) == 38792879000000
    assert int(m["SharesOutstanding"]["value"]) == 15794987460


def test_toyota_interest_bearing_debt_uses_pattern1(toyota_result) -> None:
    """Toyota's IBD source should be 'sum of [..InterestBearingLiabilities..]'."""
    src = toyota_result.merged["InterestBearingDebt"]["source"]
    assert "InterestBearingLiabilitiesCLIFRS" in src
    assert "InterestBearingLiabilitiesNCLIFRS" in src


def test_sony_fy2024_resolves_revenue_via_issuer_namespace(sony_result) -> None:
    """Sony uses the issuer-specific SalesAndFinancialServicesRevenueIFRS."""
    src = sony_result.merged["NetSales"]["source"]
    assert "SalesAndFinancialServicesRevenueIFRS" in src
    assert int(sony_result.merged["NetSales"]["value"]) == 12957064000000


def test_sony_interest_bearing_debt_uses_pattern2(sony_result) -> None:
    """Sony's IBD aggregates Borrowings + issuer-specific long-term debt."""
    src = sony_result.merged["InterestBearingDebt"]["source"]
    assert "BorrowingsCLIFRS" in src
    # Issuer-specific elements are routed under the ISSUER alias in step3a.
    assert "ISSUER:" in src
    assert int(sony_result.merged["InterestBearingDebt"]["value"]) == 4198246000000


def test_restated_eps_extraction_for_sony() -> None:
    """The Step 7 expected restated EPS for Sony FY2022 is 162.71 (post-split)."""
    offsets, sources = xbrl_extract.extract_restated_eps_from_zip(SONY_FIXTURE, SONY_EDINET_CODE)
    # 0 = latest (FY2024), 2 = 2 years back (FY2022).
    assert offsets[0] == pytest.approx(188.71)
    assert offsets[2] == pytest.approx(162.71)
    # Sony is IFRS — every offset should be tagged as ifrs_basic.
    assert all(tag == "ifrs_basic" for tag in sources.values())


def test_restated_eps_extraction_for_toyota() -> None:
    """Toyota latest report exposes 5 fiscal years of post-split EPS."""
    offsets, sources = xbrl_extract.extract_restated_eps_from_zip(TOYOTA_FIXTURE, TOYOTA_EDINET_CODE)
    # Latest period EPS matches the raw figure (no split in window).
    assert offsets[0] == pytest.approx(359.56)
    # At least 3 years of history should be present.
    assert len(offsets) >= 3
    # Toyota is IFRS — ifrs_basic should be used throughout.
    assert sources[0] == "ifrs_basic"

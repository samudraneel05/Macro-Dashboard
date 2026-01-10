"""
Global Macro Dashboard — Validate Layer
========================================
Data quality assertions that run after Transform, before Load.

Each assertion checks a specific quality property and returns a
ValidationResult. Failures are logged as WARNINGS (never crash the
pipeline) and written to output/validation_report.txt.

All 7 checks run unconditionally so you get a full picture of data
quality in every pipeline run.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

import config

logger = logging.getLogger(__name__)


# ============================================================================
# Validation Result
# ============================================================================

@dataclass
class ValidationResult:
    """Outcome of a single validation check."""
    check_name: str
    passed: bool
    message: str
    details: list = field(default_factory=list)  # optional detail lines


# ============================================================================
# Assertion Functions
# ============================================================================

def assert_no_null_dates(tables):
    """
    Check 1: No date column in any table contains NaN/null values.

    Parameters
    ----------
    tables : dict[str, pd.DataFrame]

    Returns
    -------
    ValidationResult
    """
    issues = []

    for name, df in tables.items():
        if "date" in df.columns:
            null_count = df["date"].isnull().sum()
            if null_count > 0:
                issues.append(f"  {name}: {null_count} null dates")

    if issues:
        return ValidationResult(
            check_name="assert_no_null_dates",
            passed=False,
            message=f"Found null dates in {len(issues)} table(s)",
            details=issues,
        )

    return ValidationResult(
        check_name="assert_no_null_dates",
        passed=True,
        message="All date columns are complete (no nulls)",
    )


def assert_positive_gdp(tables):
    """
    Check 2: GDP values are non-negative.

    Checks fact_us_economic (FRED_GDPC1) and fact_global_structural (WB_NY.GDP.MKTP.CD).

    Returns
    -------
    ValidationResult
    """
    issues = []

    # FRED GDP
    fact_us = tables.get("fact_us_economic", pd.DataFrame())
    if not fact_us.empty and "indicator_id" in fact_us.columns:
        gdp_rows = fact_us[fact_us["indicator_id"] == "FRED_GDPC1"]
        negative = gdp_rows[gdp_rows["value"] < 0]
        if not negative.empty:
            issues.append(f"  fact_us_economic (FRED_GDPC1): {len(negative)} negative GDP values")

    # World Bank GDP
    fact_wb = tables.get("fact_global_structural", pd.DataFrame())
    if not fact_wb.empty and "indicator_id" in fact_wb.columns:
        gdp_rows = fact_wb[fact_wb["indicator_id"] == "WB_NY.GDP.MKTP.CD"]
        negative = gdp_rows[gdp_rows["value"] < 0]
        if not negative.empty:
            issues.append(f"  fact_global_structural (WB GDP): {len(negative)} negative GDP values")

    if issues:
        return ValidationResult(
            check_name="assert_positive_gdp",
            passed=False,
            message=f"Found negative GDP values in {len(issues)} table(s)",
            details=issues,
        )

    return ValidationResult(
        check_name="assert_positive_gdp",
        passed=True,
        message="All GDP values are non-negative",
    )


def assert_rate_bounds(tables):
    """
    Check 3: Interest rates and unemployment rates are within -5% to 100%.

    Checks FRED series (FEDFUNDS, GS10, UNRATE) and WB unemployment.

    Returns
    -------
    ValidationResult
    """
    RATE_INDICATORS = [
        "FRED_FEDFUNDS", "FRED_GS10", "FRED_UNRATE",
        "WB_SL.UEM.TOTL.ZS",
    ]

    issues = []

    for table_name in ["fact_us_economic", "fact_global_structural"]:
        df = tables.get(table_name, pd.DataFrame())
        if df.empty or "indicator_id" not in df.columns:
            continue

        for ind_id in RATE_INDICATORS:
            subset = df[df["indicator_id"] == ind_id].dropna(subset=["value"])
            if subset.empty:
                continue

            out_of_bounds = subset[(subset["value"] > 100) | (subset["value"] < -5)]
            if not out_of_bounds.empty:
                issues.append(
                    f"  {table_name}/{ind_id}: {len(out_of_bounds)} values outside [-5, 100] "
                    f"(min={out_of_bounds['value'].min():.2f}, max={out_of_bounds['value'].max():.2f})"
                )

    if issues:
        return ValidationResult(
            check_name="assert_rate_bounds",
            passed=False,
            message=f"Found {len(issues)} rate indicator(s) with out-of-bounds values",
            details=issues,
        )

    return ValidationResult(
        check_name="assert_rate_bounds",
        passed=True,
        message="All rate indicators within [-5%, 100%]",
    )


def assert_row_count(tables):
    """
    Check 4: Each fact table has a minimum expected number of rows.

    Minimum thresholds are deliberately conservative — they catch total
    extraction failures without being brittle to normal data variations.

    Returns
    -------
    ValidationResult
    """
    MIN_ROWS = {
        "fact_us_economic": 100,         # ~6 series × ~120 months = 720+ expected
        "fact_global_structural": 50,    # ~9 indicators × 19 countries × ~10 years
        "fact_global_macro": 50,         # ~5 indicators × 19 countries × ~10 years
        "fact_market_daily": 100,        # ~5 symbols × ~2500 trading days
        "fact_forex_daily": 50,          # ~3 pairs × ~2500 trading days
    }

    issues = []

    for table_name, min_count in MIN_ROWS.items():
        df = tables.get(table_name, pd.DataFrame())
        actual = len(df)
        if actual < min_count:
            issues.append(
                f"  {table_name}: {actual} rows (minimum expected: {min_count})"
            )

    if issues:
        return ValidationResult(
            check_name="assert_row_count",
            passed=False,
            message=f"{len(issues)} table(s) below minimum row count",
            details=issues,
        )

    return ValidationResult(
        check_name="assert_row_count",
        passed=True,
        message="All fact tables meet minimum row count thresholds",
    )


def assert_no_duplicate_keys(tables):
    """
    Check 5: No duplicate composite key rows in fact tables.

    Key definitions:
      - fact_us_economic:        (date, indicator_id)
      - fact_global_structural:  (date, country_code, indicator_id)
      - fact_market_daily:       (date, symbol)
      - fact_forex_daily:        (date, pair)

    Returns
    -------
    ValidationResult
    """
    KEY_COLS = {
        "fact_us_economic":        ["date", "indicator_id"],
        "fact_global_structural":  ["date", "country_code", "indicator_id"],
        "fact_global_macro":       ["date", "country_code", "indicator_id"],
        "fact_market_daily":       ["date", "symbol"],
        "fact_forex_daily":        ["date", "pair"],
    }

    issues = []

    for table_name, key_cols in KEY_COLS.items():
        df = tables.get(table_name, pd.DataFrame())
        if df.empty:
            continue

        # Only check columns that exist in the table
        existing_keys = [c for c in key_cols if c in df.columns]
        if not existing_keys:
            continue

        dup_count = df.duplicated(subset=existing_keys).sum()
        if dup_count > 0:
            issues.append(
                f"  {table_name}: {dup_count} duplicate rows on key {existing_keys}"
            )

    if issues:
        return ValidationResult(
            check_name="assert_no_duplicate_keys",
            passed=False,
            message=f"Found duplicates in {len(issues)} table(s)",
            details=issues,
        )

    return ValidationResult(
        check_name="assert_no_duplicate_keys",
        passed=True,
        message="No duplicate composite keys in any fact table",
    )


def assert_date_range(tables):
    """
    Check 6: All dates are within the configured extraction range.

    Compares against config.START_DATE and config.END_DATE.

    Returns
    -------
    ValidationResult
    """
    start = pd.Timestamp(config.START_DATE)
    end = pd.Timestamp(config.END_DATE)

    issues = []

    for name, df in tables.items():
        if not name.startswith("fact_") or "date" not in df.columns:
            continue

        dates = pd.to_datetime(df["date"], errors="coerce")
        valid_dates = dates.dropna()

        if valid_dates.empty:
            continue

        before = (valid_dates < start).sum()

        # fact_global_macro intentionally contains IMF forecast years
        # (up to ~5 years past the end date). Allow a 6-year tolerance
        # past END_DATE for that table only.
        if name == "fact_global_macro":
            forecast_horizon = end + pd.DateOffset(years=6)
            after = (valid_dates > forecast_horizon).sum()
        else:
            after = (valid_dates > end).sum()

        if before > 0:
            issues.append(
                f"  {name}: {before} dates before {config.START_DATE}"
            )
        if after > 0:
            issues.append(
                f"  {name}: {after} dates after {end.strftime('%Y-%m-%d')} (start + 6yr tolerance)"
            )

    if issues:
        return ValidationResult(
            check_name="assert_date_range",
            passed=False,
            message=f"Found out-of-range dates in {len(issues)} case(s)",
            details=issues,
        )

    return ValidationResult(
        check_name="assert_date_range",
        passed=True,
        message=f"All dates within [{config.START_DATE}, {end.strftime('%Y-%m-%d')}]",
    )


def assert_forecast_flag(tables):
    """
    Check 7: IMF forecast rows in fact_global_macro are properly flagged.

    Validates that:
      - Every row with year > current year has is_forecast = True
      - No historical row (year <= current year) is flagged is_forecast = True
      - The is_forecast column exists and is boolean

    Returns
    -------
    ValidationResult
    """
    df = tables.get("fact_global_macro", pd.DataFrame())

    # If the table is empty or missing, skip gracefully (extraction may have failed)
    if df.empty or "is_forecast" not in df.columns or "date" not in df.columns:
        return ValidationResult(
            check_name="assert_forecast_flag",
            passed=True,
            message="fact_global_macro empty or missing — skipped",
            details=[],
        )

    issues = []

    dates = pd.to_datetime(df["date"], errors="coerce")
    years = dates.dt.year
    current_year = config.CURRENT_YEAR

    # Future rows must be flagged as forecast
    future_mask = years > current_year
    unflagged_forecasts = df[future_mask & ~df["is_forecast"].astype(bool)]
    if not unflagged_forecasts.empty:
        issues.append(
            f"  {len(unflagged_forecasts)} future-year rows missing is_forecast=True "
            f"(years: {sorted(years[future_mask & ~df['is_forecast'].astype(bool)].unique())[:5]})"
        )

    # Historical rows must NOT be flagged as forecast
    historical_mask = years <= current_year
    misflagged_history = df[historical_mask & df["is_forecast"].astype(bool)]
    if not misflagged_history.empty:
        issues.append(
            f"  {len(misflagged_history)} historical rows incorrectly flagged is_forecast=True "
            f"(years: {sorted(years[historical_mask & df['is_forecast'].astype(bool)].unique())[:5]})"
        )

    if issues:
        return ValidationResult(
            check_name="assert_forecast_flag",
            passed=False,
            message="IMF forecast flags inconsistent with year values",
            details=issues,
        )

    n_forecasts = int(df["is_forecast"].astype(bool).sum())
    return ValidationResult(
        check_name="assert_forecast_flag",
        passed=True,
        message=f"IMF forecast flags correct ({n_forecasts} forecast rows flagged)",
    )


# ============================================================================
# Master Validation Runner
# ============================================================================

ALL_CHECKS = [
    assert_no_null_dates,
    assert_positive_gdp,
    assert_rate_bounds,
    assert_row_count,
    assert_no_duplicate_keys,
    assert_date_range,
    assert_forecast_flag,
]


def run_validations(tables):
    """
    Run all 7 data quality checks and return results.

    Failures are logged as warnings — they never crash the pipeline.
    Results are also written to output/validation_report.txt.

    Parameters
    ----------
    tables : dict[str, pd.DataFrame]
        The transformed tables from run_transforms().

    Returns
    -------
    list[ValidationResult]
        Results for all 7 checks.
    """
    logger.info("=" * 50)
    logger.info("Running %d validation checks...", len(ALL_CHECKS))
    logger.info("=" * 50)

    results = []

    for check_fn in ALL_CHECKS:
        try:
            result = check_fn(tables)
        except Exception as exc:
            logger.error("Validation check %s raised an exception: %s", check_fn.__name__, exc)
            result = ValidationResult(
                check_name=check_fn.__name__,
                passed=False,
                message=f"Exception during check: {exc}",
            )

        results.append(result)

        if result.passed:
            logger.info("  ✅ %s — %s", result.check_name, result.message)
        else:
            logger.warning("  ⚠️  %s — %s", result.check_name, result.message)
            for detail in result.details:
                logger.warning("     %s", detail)

    passed = sum(1 for r in results if r.passed)
    failed = len(results) - passed
    logger.info(
        "Validation complete: %d/%d passed, %d failed",
        passed, len(results), failed,
    )

    # Write report to file
    _write_report(results)

    return results


def _write_report(results):
    """Write a human-readable validation report to output/validation_report.txt."""
    import os
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    report_path = os.path.join(config.OUTPUT_DIR, "validation_report.txt")

    passed = sum(1 for r in results if r.passed)
    failed = len(results) - passed

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("=" * 65 + "\n")
        f.write("  VALIDATION REPORT\n")
        f.write(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 65 + "\n\n")

        f.write(f"  Summary: {passed}/{len(results)} passed, {failed} failed\n\n")

        for result in results:
            status = "✅ PASS" if result.passed else "❌ FAIL"
            f.write(f"[{status}] {result.check_name}\n")
            f.write(f"  {result.message}\n")
            for detail in result.details:
                f.write(f"  {detail}\n")
            f.write("\n")

        f.write("=" * 65 + "\n")
        f.write("  END OF REPORT\n")
        f.write("=" * 65 + "\n")

    logger.info("Validation report written to %s", report_path)

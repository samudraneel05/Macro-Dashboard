"""
Global Macro Dashboard — Transform Layer
=========================================
Transforms raw API data (dicts/lists from extract.py) into clean,
Power BI-ready Pandas DataFrames in Star Schema format.

Produces:
  - 3 dimension tables: dim_date, dim_country, dim_indicator
  - 5 fact tables:       fact_us_economic, fact_global_structural,
                         fact_global_macro, fact_market_daily, fact_forex_daily

All calculated fields (pct_change, yoy_change, moving averages, volatility)
are computed here using Pandas and NumPy.
"""

import logging
from datetime import datetime

import numpy as np
import pandas as pd

import config

logger = logging.getLogger(__name__)


# ============================================================================
# Dimension Tables
# ============================================================================

def build_dim_date(start_date=None, end_date=None):
    """
    Generate a complete calendar dimension table.

    Parameters
    ----------
    start_date : str, optional
        Start date 'YYYY-MM-DD'. Defaults to config.START_DATE.
    end_date : str, optional
        End date 'YYYY-MM-DD'. Defaults to config.END_DATE.

    Returns
    -------
    pd.DataFrame
        Columns: date, year, quarter, month, month_name, day_of_week, is_weekend
    """
    start_date = start_date or config.START_DATE
    end_date = end_date or config.END_DATE

    # Extend the calendar 6 years past end_date so IMF forecast rows in
    # fact_global_macro (projected up to ~5 years ahead) still join to
    # dim_date in the Power BI model.
    extended_end = pd.Timestamp(end_date) + pd.DateOffset(years=6)

    dates = pd.date_range(start=start_date, end=extended_end, freq="D")
    df = pd.DataFrame({"date": dates})

    df["year"] = df["date"].dt.year
    df["quarter"] = df["date"].dt.quarter
    df["month"] = df["date"].dt.month
    df["month_name"] = df["date"].dt.month_name()
    df["day_of_week"] = df["date"].dt.day_name()
    df["is_weekend"] = df["date"].dt.dayofweek >= 5  # Sat=5, Sun=6

    # Format date column as string for CSV output
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")

    logger.info(
        "dim_date: %d rows (%s to %s, extended to %s for forecasts)",
        len(df), start_date, end_date, extended_end.strftime("%Y-%m-%d"),
    )
    return df


def build_dim_country():
    """
    Build the country dimension table from the static lookup in config.

    Returns
    -------
    pd.DataFrame
        Columns: country_code, country_name, region
    """
    rows = []
    for code, info in config.COUNTRY_LOOKUP.items():
        rows.append({
            "country_code": code,
            "country_name": info["name"],
            "region": info["region"],
        })

    df = pd.DataFrame(rows)
    df = df.sort_values("country_code").reset_index(drop=True)

    logger.info("dim_country: %d rows", len(df))
    return df


def build_dim_indicator():
    """
    Build the indicator dimension table — a catalog of every metric
    across all four data sources, with prefixed IDs to prevent collisions.

    Returns
    -------
    pd.DataFrame
        Columns: indicator_id, indicator_name, source, unit, frequency
    """
    rows = []

    # FRED indicators
    for sid, meta in config.FRED_SERIES.items():
        rows.append({
            "indicator_id": f"FRED_{sid}",
            "indicator_name": meta["name"],
            "source": "FRED",
            "unit": meta["unit"],
            "frequency": meta["frequency"],
        })

    # World Bank indicators
    for code, meta in config.WB_INDICATORS.items():
        rows.append({
            "indicator_id": f"WB_{code}",
            "indicator_name": meta["name"],
            "source": "WorldBank",
            "unit": meta["unit"],
            "frequency": meta["frequency"],
        })

    # IMF indicators
    for code, meta in config.IMF_INDICATORS.items():
        rows.append({
            "indicator_id": f"IMF_{code}",
            "indicator_name": meta["name"],
            "source": "IMF",
            "unit": meta["unit"],
            "frequency": meta["frequency"],
        })

    # Yahoo Finance — stock symbols as indicators
    for sym, meta in config.YFINANCE_STOCK_SYMBOLS.items():
        rows.append({
            "indicator_id": f"YF_{sym}",
            "indicator_name": meta["display_name"],
            "source": "YahooFinance",
            "unit": "Price (USD)",
            "frequency": "Daily",
        })

    # Yahoo Finance — forex pairs as indicators
    for sym, meta in config.YFINANCE_FOREX_SYMBOLS.items():
        rows.append({
            "indicator_id": f"YF_{sym}",
            "indicator_name": meta["display_name"],
            "source": "YahooFinance",
            "unit": "Exchange Rate",
            "frequency": "Daily",
        })

    df = pd.DataFrame(rows)
    logger.info("dim_indicator: %d rows", len(df))
    return df


# ============================================================================
# Fact Table: US Economic (FRED)
# ============================================================================

def transform_fred(fred_raw):
    """
    Transform raw FRED observations into fact_us_economic DataFrame.

    Steps:
      1. Parse each series' observations into a per-series DataFrame [date, value]
      2. Convert "." → NaN via pd.to_numeric(errors='coerce')
      3. Convert date strings → pd.Timestamp
      4. Calculate pct_change (period-over-period)
      5. Calculate yoy_change (shift by 12 for monthly, 4 for quarterly)
      6. Melt all series into long-format with indicator_id column

    Parameters
    ----------
    fred_raw : dict[str, list[dict]]
        Output of extract_fred(): {series_id: [{"date": ..., "value": ...}, ...]}

    Returns
    -------
    pd.DataFrame
        Columns: date, indicator_id, value, pct_change, yoy_change
    """
    if not fred_raw:
        logger.warning("FRED raw data is empty — returning empty DataFrame")
        return pd.DataFrame(columns=["date", "indicator_id", "value", "pct_change", "yoy_change"])

    all_series = []

    for series_id, observations in fred_raw.items():
        if not observations:
            logger.warning("FRED series %s has no observations — skipping", series_id)
            continue

        # Step 1: Parse into DataFrame
        df = pd.DataFrame(observations)

        # Step 2: Convert "." to NaN (FRED gotcha)
        df["value"] = pd.to_numeric(df["value"], errors="coerce")

        # Step 3: Convert date strings to Timestamp
        df["date"] = pd.to_datetime(df["date"])

        # Sort chronologically
        df = df.sort_values("date").reset_index(drop=True)

        # Step 4: Period-over-period change
        # Step 5: Year-over-year change
        # Quarterly series (GDPC1) → shift by 4; monthly → shift by 12
        frequency = config.FRED_SERIES.get(series_id, {}).get("frequency", "Monthly")
        yoy_shift = 4 if frequency == "Quarterly" else 12

        if series_id in config.FRED_RATE_SERIES:
            # Rate series (e.g. Fed Funds, 10Y yield, unemployment):
            # absolute difference in percentage points.
            df["pct_change"] = df["value"].diff()
            df["yoy_change"] = df["value"].diff(periods=yoy_shift)
        else:
            # Level series (e.g. CPI index, GDP in USD):
            # relative percentage change.
            df["pct_change"] = df["value"].pct_change() * 100
            df["yoy_change"] = df["value"].pct_change(periods=yoy_shift) * 100

        # Step 6: Add indicator_id with FRED_ prefix
        df["indicator_id"] = f"FRED_{series_id}"

        all_series.append(df[["date", "indicator_id", "value", "pct_change", "yoy_change"]])

        logger.debug(
            "FRED %s: %d rows after transform (%.1f%% non-null values)",
            series_id, len(df), df["value"].notna().mean() * 100,
        )

    if not all_series:
        logger.warning("No FRED series produced data — returning empty DataFrame")
        return pd.DataFrame(columns=["date", "indicator_id", "value", "pct_change", "yoy_change"])

    # Concatenate all series into one long-format fact table
    result = pd.concat(all_series, ignore_index=True)

    # Format date as string for CSV
    result["date"] = result["date"].dt.strftime("%Y-%m-%d")

    logger.info("fact_us_economic: %d rows across %d indicators", len(result), len(all_series))
    return result


# ============================================================================
# Fact Table: Global Structural (World Bank)
# ============================================================================

def transform_world_bank(wb_raw):
    """
    Transform raw World Bank records into fact_global_structural DataFrame.

    Steps:
      1. Flatten records into DataFrame [indicator_id, country_code, date, value]
      2. Drop rows where value is None
      3. Convert year string "2023" → "2023-01-01"
      4. Sort by [country_code, indicator_id, date]
      5. Calculate yoy_change grouped by (country_code, indicator_id)

    Parameters
    ----------
    wb_raw : dict[str, list[dict]]
        Output of extract_world_bank():
        {indicator_code: [{"indicator_id": ..., "country_code": ..., "date": ..., "value": ...}, ...]}

    Returns
    -------
    pd.DataFrame
        Columns: date, country_code, indicator_id, value, yoy_change
    """
    if not wb_raw:
        logger.warning("World Bank raw data is empty — returning empty DataFrame")
        return pd.DataFrame(columns=["date", "country_code", "indicator_id", "value", "yoy_change"])

    all_records = []

    for indicator_code, records in wb_raw.items():
        if not records:
            logger.warning("World Bank indicator %s has no records — skipping", indicator_code)
            continue

        for rec in records:
            all_records.append({
                "indicator_id": f"WB_{rec.get('indicator_id', indicator_code)}",
                "country_code": rec.get("country_code", ""),
                "date": rec.get("date", ""),
                "value": rec.get("value"),
            })

    if not all_records:
        logger.warning("No World Bank records found — returning empty DataFrame")
        return pd.DataFrame(columns=["date", "country_code", "indicator_id", "value", "yoy_change"])

    df = pd.DataFrame(all_records)

    # Step 2: Drop rows where value is None/NaN
    before_drop = len(df)
    df = df.dropna(subset=["value"]).copy()
    dropped = before_drop - len(df)
    if dropped > 0:
        logger.info("World Bank: dropped %d rows with null values", dropped)

    # Convert value to float
    df["value"] = pd.to_numeric(df["value"], errors="coerce")

    # Step 3: Convert year string to date (Jan 1 of that year)
    df["date"] = pd.to_datetime(df["date"].astype(str) + "-01-01", errors="coerce")

    # Drop rows where date conversion failed
    df = df.dropna(subset=["date"]).copy()

    # Step 4: Sort
    df = df.sort_values(["country_code", "indicator_id", "date"]).reset_index(drop=True)

    # Step 5: YoY change grouped by (country_code, indicator_id)
    # Rate indicators use absolute difference (pp); level indicators use % change.
    wb_rate_ids = {f"WB_{code}" for code in config.WB_RATE_INDICATORS}
    grouped = df.groupby(["country_code", "indicator_id"])["value"]
    yoy_pct = grouped.pct_change() * 100
    yoy_diff = grouped.diff()
    is_rate = df["indicator_id"].isin(wb_rate_ids)
    df["yoy_change"] = np.where(is_rate, yoy_diff, yoy_pct)

    # Format date for CSV
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")

    # Select final columns
    result = df[["date", "country_code", "indicator_id", "value", "yoy_change"]].copy()

    n_countries = df["country_code"].nunique()
    n_indicators = df["indicator_id"].nunique()
    logger.info(
        "fact_global_structural: %d rows (%d countries × %d indicators)",
        len(result), n_countries, n_indicators,
    )
    return result


# ============================================================================
# Fact Table: Global Macro (IMF)
# ============================================================================

def transform_imf(imf_raw):
    """
    Transform raw IMF DataMapper data into fact_global_macro DataFrame.

    Steps:
      1. Flatten the triple-nested dict {indicator: {country: {year: value}}}
         into a DataFrame [date, country_code, indicator_id, value]
      2. Convert string values → float via pd.to_numeric(errors='coerce')
      3. Convert year strings → pd.Timestamp (Jan 1 of the year)
      4. Flag is_forecast = True for any year > current year (IMF projection)
      5. Calculate yoy_change grouped by (country_code, indicator_id)

    Parameters
    ----------
    imf_raw : dict[str, dict[str, dict[str, str]]]
        Output of extract_imf():
        {indicator_code: {country_code: {year: value_string}}}

    Returns
    -------
    pd.DataFrame
        Columns: date, country_code, indicator_id, value, is_forecast, yoy_change
    """
    if not imf_raw:
        logger.warning("IMF raw data is empty — returning empty DataFrame")
        return pd.DataFrame(
            columns=["date", "country_code", "indicator_id", "value", "is_forecast", "yoy_change"]
        )

    all_records = []

    # The IMF response contains every country (~230) even when specific
    # codes are in the URL path — filter down to the G20 set we track.
    wanted = set(config.IMF_COUNTRY_CODES)

    for indicator_code, countries in imf_raw.items():
        if not countries:
            logger.warning("IMF indicator %s has no country data — skipping", indicator_code)
            continue

        for country_code, year_values in countries.items():
            if country_code not in wanted:
                continue
            if not isinstance(year_values, dict):
                continue
            for year, value in year_values.items():
                all_records.append({
                    "indicator_id": f"IMF_{indicator_code}",
                    "country_code": country_code,
                    "year": str(year),
                    "value": value,
                })

    if not all_records:
        logger.warning("No IMF records found — returning empty DataFrame")
        return pd.DataFrame(
            columns=["date", "country_code", "indicator_id", "value", "is_forecast", "yoy_change"]
        )

    df = pd.DataFrame(all_records)

    # Step 2: Convert value to float (IMF returns strings)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")

    # Drop rows where value failed to parse
    before_drop = len(df)
    df = df.dropna(subset=["value"]).copy()
    dropped = before_drop - len(df)
    if dropped > 0:
        logger.info("IMF: dropped %d rows with unparseable values", dropped)

    # Step 3: Convert year string → date (Jan 1 of the year)
    df["date"] = pd.to_datetime(df["year"] + "-01-01", errors="coerce")
    df = df.dropna(subset=["date"]).copy()
    df["year_int"] = df["date"].dt.year

    # Keep only years within the pipeline's configured window onwards —
    # dim_date starts at config.START_DATE, so earlier years would be
    # orphan FKs. Forecasts (future years) are kept and flagged below.
    start_year = pd.Timestamp(config.START_DATE).year
    before_trim = len(df)
    df = df[df["year_int"] >= start_year].copy()
    trimmed = before_trim - len(df)
    if trimmed > 0:
        logger.info("IMF: dropped %d rows before %d (outside pipeline window)", trimmed, start_year)

    # Step 4: Flag forecasts — any year strictly after the current year
    df["is_forecast"] = df["year_int"] > config.CURRENT_YEAR

    # Step 5: YoY change grouped by (country_code, indicator_id)
    # All IMF indicators tracked are rates/percentages → use absolute difference (pp)
    # where applicable; fall back to % change for any future level indicators.
    df = df.sort_values(["country_code", "indicator_id", "date"]).reset_index(drop=True)
    imf_rate_ids = {f"IMF_{code}" for code in config.IMF_RATE_INDICATORS}
    grouped = df.groupby(["country_code", "indicator_id"])["value"]
    yoy_pct = grouped.pct_change() * 100
    yoy_diff = grouped.diff()
    is_rate = df["indicator_id"].isin(imf_rate_ids)
    df["yoy_change"] = np.where(is_rate, yoy_diff, yoy_pct)

    # Format date for CSV
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")

    # Select final columns
    result = df[["date", "country_code", "indicator_id", "value", "is_forecast", "yoy_change"]].copy()

    n_countries = df["country_code"].nunique()
    n_indicators = df["indicator_id"].nunique()
    n_forecasts = int(df["is_forecast"].sum())
    logger.info(
        "fact_global_macro: %d rows (%d countries × %d indicators, %d forecasts)",
        len(result), n_countries, n_indicators, n_forecasts,
    )
    return result


# ============================================================================
# Fact Table: Market Daily (Yahoo Finance — Stocks)
# ============================================================================

def transform_yfinance_stocks(yfinance_raw):
    """
    Transform raw yfinance stock candle data into fact_market_daily DataFrame.

    Steps:
      1. Convert records into DataFrame
      2. Convert date strings → Timestamp
      3. Calculate daily_return_pct
      4. Calculate ma_50 (50-day moving average)
      5. Calculate ma_200 (200-day moving average)
      6. Calculate volatility_20d (20-day rolling std dev of returns)

    Parameters
    ----------
    yfinance_raw : dict
        The "stocks" sub-dict from extract_yfinance():
        {symbol: {"display_name": ..., "candles": [{"date": ..., "o": ..., ...}]}}

    Returns
    -------
    pd.DataFrame
        Columns: date, symbol, display_name, open, high, low, close,
                 volume, daily_return_pct, ma_50, ma_200, volatility_20d
    """
    stocks = yfinance_raw.get("stocks", {}) if isinstance(yfinance_raw, dict) else {}

    if not stocks:
        logger.warning("No Yahoo Finance stock data — returning empty DataFrame")
        return pd.DataFrame(columns=[
            "date", "symbol", "display_name", "indicator_id", "open", "high", "low", "close",
            "volume", "daily_return_pct", "ma_50", "ma_200", "volatility_20d",
        ])

    all_frames = []

    for symbol, data in stocks.items():
        candles = data.get("candles", [])
        display_name = data.get("display_name", symbol)

        if not candles:
            logger.warning("Yahoo Finance stock %s: no candle data — skipping", symbol)
            continue

        # Step 1: Build DataFrame from records
        df = pd.DataFrame(candles)
        df = df.rename(columns={
            "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"
        })

        # Step 2: Convert date
        df["date"] = pd.to_datetime(df["date"])

        # Sort by date
        df = df.sort_values("date").reset_index(drop=True)

        # Add symbol metadata
        df["symbol"] = symbol
        df["display_name"] = display_name
        df["indicator_id"] = f"YF_{symbol}"

        # Step 3: Daily return percentage
        df["daily_return_pct"] = (df["close"] / df["close"].shift(1) - 1) * 100

        # Step 4: 50-day moving average
        df["ma_50"] = df["close"].rolling(window=50, min_periods=50).mean()

        # Step 5: 200-day moving average
        df["ma_200"] = df["close"].rolling(window=200, min_periods=200).mean()

        # Step 6: 20-day rolling volatility (std dev of daily returns)
        df["volatility_20d"] = df["daily_return_pct"].rolling(window=20, min_periods=20).std()

        # Select and order columns
        df = df[[
            "date", "symbol", "display_name", "indicator_id", "open", "high", "low", "close",
            "volume", "daily_return_pct", "ma_50", "ma_200", "volatility_20d",
        ]].copy()

        all_frames.append(df)
        logger.debug("Yahoo Finance stock %s (%s): %d candles transformed", symbol, display_name, len(df))

    if not all_frames:
        logger.warning("No stock candle data produced — returning empty DataFrame")
        return pd.DataFrame(columns=[
            "date", "symbol", "display_name", "indicator_id", "open", "high", "low", "close",
            "volume", "daily_return_pct", "ma_50", "ma_200", "volatility_20d",
        ])

    result = pd.concat(all_frames, ignore_index=True)

    # Format date for CSV
    result["date"] = result["date"].dt.strftime("%Y-%m-%d")

    # Ensure volume is integer (handle NaN gracefully)
    result["volume"] = result["volume"].fillna(0).astype(np.int64)

    logger.info(
        "fact_market_daily: %d rows across %d symbols",
        len(result), result["symbol"].nunique(),
    )
    return result


# ============================================================================
# Fact Table: Forex Daily (Yahoo Finance — Forex)
# ============================================================================

def transform_yfinance_forex(yfinance_raw):
    """
    Transform raw yfinance forex candle data into fact_forex_daily DataFrame.

    Steps:
      1. Convert records into DataFrame
      2. Convert date strings → Timestamp
      3. Calculate daily_change_pct

    Parameters
    ----------
    yfinance_raw : dict
        The "forex" sub-dict from extract_yfinance():
        {symbol: {"display_name": ..., "pair": ..., "candles": [...]}}

    Returns
    -------
    pd.DataFrame
        Columns: date, pair, open, high, low, close, daily_change_pct
    """
    forex = yfinance_raw.get("forex", {}) if isinstance(yfinance_raw, dict) else {}

    if not forex:
        logger.warning("No Yahoo Finance forex data — returning empty DataFrame")
        return pd.DataFrame(columns=[
            "date", "pair", "indicator_id", "open", "high", "low", "close", "daily_change_pct",
        ])

    all_frames = []

    for symbol, data in forex.items():
        candles = data.get("candles", [])
        pair = data.get("pair", symbol)

        if not candles:
            logger.warning("Yahoo Finance forex %s: no candle data — skipping", symbol)
            continue

        # Step 1: Build DataFrame from records
        df = pd.DataFrame(candles)
        df = df.rename(columns={
            "o": "open", "h": "high", "l": "low", "c": "close"
        })

        # Step 2: Convert date
        df["date"] = pd.to_datetime(df["date"])

        # Sort by date
        df = df.sort_values("date").reset_index(drop=True)

        # Add pair identifier
        df["pair"] = pair
        df["indicator_id"] = f"YF_{symbol}"

        # Step 3: Daily change percentage
        df["daily_change_pct"] = (df["close"] / df["close"].shift(1) - 1) * 100

        # Select columns
        df = df[["date", "pair", "indicator_id", "open", "high", "low", "close", "daily_change_pct"]].copy()

        all_frames.append(df)
        logger.debug("Yahoo Finance forex %s (%s): %d candles transformed", symbol, pair, len(df))

    if not all_frames:
        logger.warning("No forex candle data produced — returning empty DataFrame")
        return pd.DataFrame(columns=[
            "date", "pair", "indicator_id", "open", "high", "low", "close", "daily_change_pct",
        ])

    result = pd.concat(all_frames, ignore_index=True)

    # Format date for CSV
    result["date"] = result["date"].dt.strftime("%Y-%m-%d")

    logger.info(
        "fact_forex_daily: %d rows across %d pairs",
        len(result), result["pair"].nunique(),
    )
    return result


# ============================================================================
# Master Transform Orchestrator
# ============================================================================

def run_transforms(fred_raw, wb_raw, imf_raw, yfinance_raw):
    """
    Run all transformations sequentially and return a dictionary of DataFrames.

    Parameters
    ----------
    fred_raw : dict
        Output of extract_fred()
    wb_raw : dict
        Output of extract_world_bank()
    imf_raw : dict
        Output of extract_imf()
    yfinance_raw : dict
        Output of extract_yfinance()

    Returns
    -------
    dict[str, pd.DataFrame]
        Keys: dim_date, dim_country, dim_indicator,
              fact_us_economic, fact_global_structural, fact_global_macro,
              fact_market_daily, fact_forex_daily
    """
    logger.info("=" * 50)
    logger.info("Running all transforms...")
    logger.info("=" * 50)

    tables = {}

    # --- Dimension tables ---
    logger.info("── Dimension Tables ──")
    tables["dim_date"] = build_dim_date()
    tables["dim_country"] = build_dim_country()
    tables["dim_indicator"] = build_dim_indicator()

    # --- Fact tables ---
    logger.info("── Fact Tables ──")
    tables["fact_us_economic"] = transform_fred(fred_raw)
    tables["fact_global_structural"] = transform_world_bank(wb_raw)
    # 3. IMF — global macro policy (growth, inflation, debt, forecasts)
    tables["fact_global_macro"] = transform_imf(imf_raw)
    # 4. Markets / Forex
    yfinance_facts = transform_yfinance_stocks(yfinance_raw)
    tables["fact_market_daily"] = yfinance_facts
    tables["fact_forex_daily"] = transform_yfinance_forex(yfinance_raw)

    # --- Summary ---
    logger.info("── Transform Summary ──")
    total_rows = 0
    for name, df in tables.items():
        logger.info("  %-30s %7d rows  ×  %2d cols", name, len(df), len(df.columns))
        total_rows += len(df)
    logger.info("  %-30s %7d rows total", "GRAND TOTAL", total_rows)

    return tables

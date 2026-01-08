"""
Global Macro Dashboard — Extract Layer
=======================================
One function per API source. Each function handles:
  - HTTP requests with timeout, retries, and exponential backoff
  - Rate-limit-safe sleeps between requests
  - Graceful handling of empty/malformed responses
  - Structured logging of every request

Returns raw data structures (dicts/lists) — no Pandas here.
All transformation happens downstream in transform.py.
"""

import logging
from datetime import datetime
import time
import ssl

# Fix macOS SSL certificate errors for pandas read_csv
ssl._create_default_https_context = ssl._create_unverified_context

import pandas as pd
import requests
import yfinance as yf

import config

logger = logging.getLogger(__name__)


# ============================================================================
# Shared HTTP helper
# ============================================================================

def _request_with_retry(url, params=None, headers=None, max_retries=None):
    """
    Make a GET request with exponential-backoff retry logic.

    Handles:
      - HTTP 429 (rate limited) → retry with backoff
      - HTTP 5xx (server error) → retry with backoff
      - Network timeout           → retry once
      - Malformed JSON            → return None

    Returns:
        dict | list | None — parsed JSON, or None on failure.
    """
    if max_retries is None:
        max_retries = config.MAX_RETRIES

    for attempt in range(1, max_retries + 1):
        try:
            logger.debug(
                "Request [attempt %d/%d]: GET %s | params=%s",
                attempt, max_retries, url, params,
            )

            resp = requests.get(
                url,
                params=params,
                headers=headers,
                timeout=config.REQUEST_TIMEOUT,
            )

            # --- Rate limited ---
            if resp.status_code == 429:
                wait = config.RETRY_BACKOFF_BASE ** attempt
                logger.warning(
                    "HTTP 429 (rate limited) on %s — retrying in %ds", url, wait,
                )
                time.sleep(wait)
                continue

            # --- Server error ---
            if resp.status_code >= 500:
                wait = config.RETRY_BACKOFF_BASE ** attempt
                logger.warning(
                    "HTTP %d on %s — retrying in %ds",
                    resp.status_code, url, wait,
                )
                time.sleep(wait)
                continue

            # --- Client error (except 429) ---
            if resp.status_code >= 400:
                logger.error(
                    "HTTP %d on %s — not retrying (client error). Body: %s",
                    resp.status_code, url, resp.text[:500],
                )
                return None

            # --- Success ---
            return resp.json()

        except requests.exceptions.Timeout:
            logger.warning("Timeout on %s (attempt %d/%d)", url, attempt, max_retries)
            if attempt < max_retries:
                time.sleep(config.RETRY_BACKOFF_BASE ** attempt)
                continue
            logger.error("All retries exhausted (timeout) for %s", url)
            return None

        except requests.exceptions.ConnectionError as exc:
            logger.error("Connection error on %s: %s", url, exc)
            return None

        except ValueError:
            # json() decode failure
            logger.error("Malformed JSON from %s — body: %s", url, resp.text[:500])
            return None

    logger.error("All retries exhausted for %s", url)
    return None


# ============================================================================
# 1. FRED — US Economic Deep Dive
# ============================================================================

def extract_fred(
    series_ids=None,
    start_date=None,
    end_date=None,
):
    """
    Extract observation data from the FRED API for a list of series IDs.

    Parameters
    ----------
    series_ids : list[str], optional
        FRED series IDs (e.g. ["CPIAUCSL", "FEDFUNDS"]).
        Defaults to config.FRED_SERIES_IDS.
    start_date : str, optional
        Start date in YYYY-MM-DD format. Defaults to config.START_DATE.
    end_date : str, optional
        End date in YYYY-MM-DD format. Defaults to config.END_DATE.

    Returns
    -------
    dict[str, list[dict]]
        Mapping of series_id → list of observation dicts,
        each with keys "date" and "value".

    Example return::

        {
            "CPIAUCSL": [
                {"date": "2015-01-01", "value": "233.707"},
                {"date": "2015-02-01", "value": "234.722"},
                ...
            ],
            "FEDFUNDS": [...],
        }
    """
    series_ids = series_ids or config.FRED_SERIES_IDS
    start_date = start_date or config.START_DATE
    end_date = end_date or config.END_DATE

    results = {}

    for sid in series_ids:
        logger.info("Extracting FRED series: %s", sid)
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"

        try:
            df = pd.read_csv(url, parse_dates=["observation_date"])
            df = df[(df["observation_date"] >= start_date) & (df["observation_date"] <= end_date)]
            
            # The value column is named after the series ID (e.g., CPIAUCSL)
            if sid in df.columns:
                # Filter out '.' values which FRED uses for NaNs
                df = df[df[sid] != "."]
                df = df.dropna(subset=["observation_date", sid])
                
                obs_list = []
                for _, row in df.iterrows():
                    obs_list.append({
                        "date": row["observation_date"].strftime("%Y-%m-%d"),
                        "value": str(float(row[sid]))
                    })
                results[sid] = obs_list
                logger.info("  → %s: %d observations fetched", sid, len(results[sid]))
            else:
                logger.warning("  → %s: no data returned — skipping", sid)
                results[sid] = []
        except Exception as e:
            logger.error("  → %s: Error fetching data — %s", sid, str(e))
            results[sid] = []

        # Rate-limit sleep
        time.sleep(config.FRED_SLEEP)

    total = sum(len(v) for v in results.values())
    logger.info("FRED extraction complete: %d series, %d total observations", len(results), total)
    return results


# ============================================================================
# 2. World Bank — Global Structural Data
# ============================================================================

def extract_world_bank(
    indicator_codes=None,
    country_codes=None,
    date_range=None,
):
    """
    Extract indicator data from the World Bank API for G20 nations.

    Parameters
    ----------
    indicator_codes : list[str], optional
        World Bank indicator codes. Defaults to config.WB_INDICATOR_CODES.
    country_codes : str, optional
        Semicolon-separated ISO Alpha-3 codes. Defaults to config.WB_COUNTRY_CODES.
    date_range : str, optional
        Year range like "2015:2026". Defaults to config.WB_DATE_RANGE.

    Returns
    -------
    dict[str, list[dict]]
        Mapping of indicator_code → list of record dicts with keys:
        "indicator_id", "indicator_name", "country_code", "country_name",
        "date" (year string), "value".

    .. note::
        The World Bank API returns a 2-element JSON array:
        ``response[0]`` = pagination metadata,
        ``response[1]`` = actual data records.
    """
    indicator_codes = indicator_codes or config.WB_INDICATOR_CODES
    country_codes = country_codes or config.WB_COUNTRY_CODES
    date_range = date_range or config.WB_DATE_RANGE

    results = {}

    for indicator in indicator_codes:
        logger.info("Extracting World Bank indicator: %s", indicator)

        url = f"{config.WB_BASE_URL}/{country_codes}/indicator/{indicator}"
        params = {
            "format": "json",
            "date": date_range,
            "per_page": 1000,
        }

        data = _request_with_retry(url, params=params)

        # World Bank returns [metadata, records] — we want index 1
        if data and isinstance(data, list) and len(data) >= 2 and data[1]:
            raw_records = data[1]
            records = []
            for rec in raw_records:
                records.append({
                    "indicator_id": rec.get("indicator", {}).get("id", indicator),
                    "indicator_name": rec.get("indicator", {}).get("value", ""),
                    "country_code": rec.get("countryiso3code", rec.get("country", {}).get("id", "")),
                    "country_name": rec.get("country", {}).get("value", ""),
                    "date": rec.get("date", ""),
                    "value": rec.get("value"),
                })
            results[indicator] = records
            logger.info(
                "  → %s: %d records fetched", indicator, len(records),
            )
        else:
            logger.warning("  → %s: no data returned — skipping", indicator)
            results[indicator] = []

        time.sleep(config.WB_SLEEP)

    total = sum(len(v) for v in results.values())
    logger.info("World Bank extraction complete: %d indicators, %d total records", len(results), total)
    return results


# ============================================================================
# 3. IMF — Global Macro Policy Data
# ============================================================================

def extract_imf(
    indicator_codes=None,
    country_codes=None,
):
    """
    Extract fiscal & monetary policy indicators from the IMF DataMapper API.

    Parameters
    ----------
    indicator_codes : list[str], optional
        IMF indicator codes (e.g. ["NGDP_RPCH", "PCPIPCH"]).
        Defaults to config.IMF_INDICATOR_CODES.
    country_codes : list[str], optional
        ISO Alpha-3 country codes. Defaults to config.IMF_COUNTRY_CODES.

    Returns
    -------
    dict[str, dict[str, dict[str, str]]]
        Mapping of indicator_code → country_code → {year: value (string)}.

    Example return::

        {
            "NGDP_RPCH": {
                "USA": {"2020": "-2.766", "2021": "5.952", ...},
                "CHN": {...},
            },
            ...
        }

    .. note::
        The IMF edge (Akamai) rejects a spoofed browser ``User-Agent``
        with ``403 Forbidden`` because the TLS fingerprint doesn't match.
        It *allows* honest tool agents such as ``curl`` or the default
        ``python-requests`` agent, so we send only ``Accept: application/json``
        and let ``requests`` supply its default ``User-Agent``. Future years
        (up to +5) contain IMF **forecasts** with no flag — the transform
        step labels them.
    """
    indicator_codes = indicator_codes or config.IMF_INDICATOR_CODES
    country_codes = country_codes or config.IMF_COUNTRY_CODES

    # Countries are slash-separated in the URL path
    country_path = "/".join(country_codes)

    results = {}

    for indicator in indicator_codes:
        logger.info("Extracting IMF indicator: %s", indicator)

        url = f"{config.IMF_BASE_URL}/{indicator}/{country_path}"
        headers = {
            "Accept": "application/json",
            # Deliberately no custom User-Agent — a spoofed browser UA is
            # blocked by Akamai's TLS-fingerprint check; the default
            # python-requests UA is accepted.
        }

        data = _request_with_retry(url, headers=headers)

        # IMF returns {"values": {indicator_code: {country: {year: value}}}}
        if data and isinstance(data, dict):
            values = data.get("values", {})
            indicator_values = values.get(indicator, {})
            if indicator_values:
                results[indicator] = indicator_values
                n_countries = len(indicator_values)
                logger.info(
                    "  → %s: %d countries fetched", indicator, n_countries,
                )
            else:
                logger.warning("  → %s: no values returned — skipping", indicator)
                results[indicator] = {}
        else:
            logger.warning("  → %s: no data returned — skipping", indicator)
            results[indicator] = {}

        # Conservative sleep — aggressive polling triggers IP blocking
        time.sleep(config.IMF_SLEEP)

    total = sum(len(countries) for countries in results.values())
    logger.info(
        "IMF extraction complete: %d indicators, %d country-series",
        len(results), total,
    )
    return results


# ============================================================================
# 4. Yahoo Finance — Global Markets (Real-Time & Historical)
# ============================================================================

def extract_yfinance(
    stock_symbols=None,
    forex_symbols=None,
    start_date=None,
    end_date=None,
):
    """
    Extract daily market data using Yahoo Finance (yfinance).
    """
    stock_symbols = stock_symbols or config.YFINANCE_STOCK_SYMBOLS
    forex_symbols = forex_symbols or config.YFINANCE_FOREX_SYMBOLS
    start_date = start_date or config.START_DATE
    end_date = end_date or config.END_DATE

    stock_results = {}
    forex_results = {}

    # --- Stocks / Indices ---
    for symbol, meta in stock_symbols.items():
        logger.info("Extracting Yahoo Finance stock candles: %s (%s)", symbol, meta["display_name"])
        try:
            df = yf.download(symbol, start=start_date, end=end_date, progress=False)
            if not df.empty:
                # Convert the multi-index columns from yfinance to a flat dict
                # yfinance returns a DataFrame with DatetimeIndex
                df = df.reset_index()
                # If there are multiple tickers (should just be one), flatten
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                    
                df = df.rename(columns={
                    "Date": "date",
                    "Open": "o",
                    "High": "h",
                    "Low": "l",
                    "Close": "c",
                    "Volume": "v"
                })
                # Convert dates to strings
                df["date"] = df["date"].dt.strftime("%Y-%m-%d")
                
                stock_results[symbol] = {
                    "display_name": meta["display_name"],
                    "candles": df.to_dict(orient="records"),
                }
                logger.info("  → %s: %d daily candles", symbol, len(df))
            else:
                logger.warning("  → %s: No data returned — skipping", symbol)
        except Exception as e:
            logger.error("  → %s: Error fetching data — %s", symbol, str(e))

    # --- Forex ---
    for symbol, meta in forex_symbols.items():
        logger.info("Extracting Yahoo Finance forex candles: %s (%s)", symbol, meta["display_name"])
        try:
            df = yf.download(symbol, start=start_date, end=end_date, progress=False)
            if not df.empty:
                df = df.reset_index()
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                    
                df = df.rename(columns={
                    "Date": "date",
                    "Open": "o",
                    "High": "h",
                    "Low": "l",
                    "Close": "c",
                    "Volume": "v"
                })
                df["date"] = df["date"].dt.strftime("%Y-%m-%d")
                
                forex_results[symbol] = {
                    "display_name": meta["display_name"],
                    "pair": meta["pair"],
                    "candles": df.to_dict(orient="records"),
                }
                logger.info("  → %s: %d daily candles", symbol, len(df))
            else:
                logger.warning("  → %s: No data returned — skipping", symbol)
        except Exception as e:
            logger.error("  → %s: Error fetching data — %s", symbol, str(e))

    logger.info(
        "Yahoo Finance extraction complete: %d stocks, %d forex pairs",
        len(stock_results), len(forex_results),
    )
    return {"stocks": stock_results, "forex": forex_results}

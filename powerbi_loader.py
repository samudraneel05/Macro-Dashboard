"""
Power BI Data Loader
====================
Bridges the ETL pipeline and Power BI Desktop's "Python script" data source.

When you click **Refresh** in Power BI Desktop, it re-executes this script's
`get_tables()` function. Power BI imports all global pandas DataFrame objects
as tables in the Navigator window.

Two modes, controlled by the `POWERBI_FRESH` environment variable:

  POWERBI_FRESH=0  (default)  Read the cached `output/dashboard.db` SQLite
                              file produced by `python main.py`. Fast
                              (~1 second). Use this for everyday refresh.

  POWERBI_FRESH=1             Run the full extract+transform pipeline live
                              against the APIs (FRED, World Bank, IMF,
                              Yahoo Finance). Slower (~1-3 minutes) but
                              gives truly fresh data without a separate
                              `python main.py` run. Use sparingly to avoid
                              API rate limits.

Typical workflow on Windows:
  1. (Once) Run `refresh.bat` (or `python main.py`) to populate
     `output/dashboard.db`.
  2. In Power BI Desktop: Get Data > Other > Python script, paste the
     snippet from docs/power_bi_build_guide.md, load all 8 tables.
  3. To update the dashboard: run `refresh.bat` again, then click
     Refresh in Power BI Desktop (uses POWERBI_FRESH=0 by default).
  4. For a one-click live pull (no separate refresh.bat run), set the
     Windows environment variable POWERBI_FRESH=1, then click Refresh.

CLI sanity check:
  python powerbi_loader.py
"""

import logging
import os
import sqlite3
import sys

import pandas as pd

# ---------------------------------------------------------------------------
# Resolve the project directory so this file works regardless of the
# current working directory Power BI inherits.
# ---------------------------------------------------------------------------
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

# Tables Power BI must receive, in a stable order.
TABLE_NAMES = [
    "dim_date",
    "dim_country",
    "dim_indicator",
    "fact_us_economic",
    "fact_global_structural",
    "fact_global_macro",
    "fact_market_daily",
    "fact_forex_daily",
]

logger = logging.getLogger("powerbi_loader")


def _is_fresh_mode():
    """Return True if POWERBI_FRESH is set to a truthy value."""
    return os.environ.get("POWERBI_FRESH", "0").strip() in ("1", "true", "True", "yes")


def _load_from_sqlite():
    """Read all 8 tables from output/dashboard.db. Fast path."""
    import config  # noqa: F401  (ensures OUTPUT_DIR is available)

    db_path = os.path.join(config.OUTPUT_DIR, "dashboard.db")

    if not os.path.exists(db_path):
        raise FileNotFoundError(
            f"dashboard.db not found at {db_path}. "
            f"Run 'python main.py' first, or set POWERBI_FRESH=1 to pull live."
        )

    tables = {}
    conn = sqlite3.connect(db_path)
    try:
        for name in TABLE_NAMES:
            # Use read_sql_query (works with a raw sqlite3 connection;
            # read_sql_table would require SQLAlchemy).
            df = pd.read_sql_query(f"SELECT * FROM \"{name}\"", conn)
            tables[name] = df
    finally:
        conn.close()

    # SQLite has no boolean type — bool columns (is_forecast, is_weekend)
    # are stored as 0/1 integers. Cast them back to bool so Power BI sees
    # the same True/False type in cached mode as in fresh mode.
    for name, df in tables.items():
        for col in ("is_forecast", "is_weekend"):
            if col in df.columns:
                df[col] = df[col].astype(bool)

    return tables


def _load_fresh():
    """Run the full extract+transform pipeline live. Slow path.

    Skips validate/load for speed — Power BI only needs the DataFrames.
    """
    import config

    # Import lazily so SQLite-mode users don't pay the import cost of
    # requests/yfinance if they're not installed.
    from pipeline.extract import (
        extract_fred,
        extract_world_bank,
        extract_imf,
        extract_yfinance,
    )
    from pipeline.transform import run_transforms

    # Use the configured date range (defaults to 2015-01-01 → today).
    start_date = config.START_DATE
    end_date = config.END_DATE

    fred_data = extract_fred(start_date=start_date, end_date=end_date)
    wb_data = extract_world_bank()
    imf_data = extract_imf()
    yfinance_data = extract_yfinance(start_date=start_date, end_date=end_date)

    tables = run_transforms(fred_data, wb_data, imf_data, yfinance_data)
    return tables


def get_tables():
    """
    Return a dict of {table_name: pd.DataFrame} for all 8 star-schema tables.

    This is the function Power BI Desktop's Python data source calls.
    It must return a dict of pandas DataFrames.
    """
    fresh = _is_fresh_mode()

    if fresh:
        logger.info("POWERBI_FRESH=1 — running live extract+transform")
        try:
            tables = _load_fresh()
        except Exception as exc:
            # Fall back to SQLite if the live pull fails, so Refresh
            # never hard-errors the report.
            logger.warning("Live pull failed (%s) — falling back to SQLite", exc)
            tables = _load_from_sqlite()
    else:
        tables = _load_from_sqlite()

    # Ensure every expected table is present and in a stable order.
    result = {}
    for name in TABLE_NAMES:
        df = tables.get(name)
        if df is None:
            logger.warning("Table '%s' missing — returning empty DataFrame", name)
            df = pd.DataFrame()
        result[name] = df

    return result


# ---------------------------------------------------------------------------
# CLI entry point — quick sanity check from a terminal.
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%H:%M:%S",
    )

    tables = get_tables()
    print("\n" + "=" * 60)
    print("  Power BI Loader — table summary")
    print("  mode: %s" % ("FRESH (live APIs)" if _is_fresh_mode() else "CACHED (SQLite)"))
    print("=" * 60)
    total = 0
    for name in TABLE_NAMES:
        df = tables[name]
        rows = len(df)
        cols = len(df.columns) if hasattr(df, "columns") else 0
        total += rows
        print(f"  {name:<28} {rows:>8} rows × {cols:>2} cols")
    print("-" * 60)
    print(f"  {'TOTAL':<28} {total:>8} rows")
    print("=" * 60)

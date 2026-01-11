"""
Global Macro Dashboard — Load Layer
====================================
Exports transformed DataFrames to CSV (and optionally SQLite)
in the output/ directory.

Each CSV is:
  - UTF-8 encoded
  - Float columns rounded to 4 decimal places
  - Logged with row count and file size
"""

import logging
import os
import sqlite3

import pandas as pd

import config

logger = logging.getLogger(__name__)


# ============================================================================
# CSV Export
# ============================================================================

def export_to_csv(tables):
    """
    Export all DataFrames to UTF-8 CSV files in output/.

    Steps:
      1. Round float columns to 4 decimal places
      2. Write to CSV without the Pandas index
      3. Log row count and file size per file

    Parameters
    ----------
    tables : dict[str, pd.DataFrame]
        Mapping of table_name → DataFrame.

    Returns
    -------
    dict[str, dict]
        Mapping of table_name → {"path": ..., "rows": ..., "size_kb": ...}
    """
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)

    export_info = {}

    for table_name, df in tables.items():
        file_path = os.path.join(config.OUTPUT_DIR, f"{table_name}.csv")

        # Round float columns to 4 decimal places
        df_out = df.copy()
        float_cols = df_out.select_dtypes(include=["float64", "float32"]).columns
        if len(float_cols) > 0:
            df_out[float_cols] = df_out[float_cols].round(4)

        # Export to CSV
        df_out.to_csv(file_path, index=False, encoding="utf-8")

        # Collect metadata
        file_size = os.path.getsize(file_path)
        size_kb = file_size / 1024

        export_info[table_name] = {
            "path": file_path,
            "rows": len(df_out),
            "columns": len(df_out.columns),
            "size_kb": round(size_kb, 1),
        }

        logger.info(
            "  %-30s → %7d rows × %2d cols  (%6.1f KB)  %s",
            table_name, len(df_out), len(df_out.columns), size_kb, file_path,
        )

    return export_info


# ============================================================================
# SQLite Export (Optional)
# ============================================================================

def export_to_sqlite(tables, db_name="dashboard.db"):
    """
    Export all DataFrames to a SQLite database for advanced querying.

    Creates output/dashboard.db with one table per DataFrame.
    Overwrites existing tables on each run.

    Parameters
    ----------
    tables : dict[str, pd.DataFrame]
        Mapping of table_name → DataFrame.
    db_name : str
        SQLite database filename. Defaults to "dashboard.db".

    Returns
    -------
    str
        Path to the created SQLite database.
    """
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    db_path = os.path.join(config.OUTPUT_DIR, db_name)

    logger.info("Exporting to SQLite: %s", db_path)

    conn = sqlite3.connect(db_path)
    try:
        for table_name, df in tables.items():
            # Round float columns
            df_out = df.copy()
            float_cols = df_out.select_dtypes(include=["float64", "float32"]).columns
            if len(float_cols) > 0:
                df_out[float_cols] = df_out[float_cols].round(4)

            df_out.to_sql(table_name, conn, if_exists="replace", index=False)
            logger.info("  SQLite: %s → %d rows", table_name, len(df_out))

        conn.commit()
    finally:
        conn.close()

    db_size = os.path.getsize(db_path) / 1024
    logger.info("SQLite export complete: %s (%.1f KB)", db_path, db_size)

    return db_path


# ============================================================================
# Master Load Runner
# ============================================================================

def run_load(tables, export_sqlite=True):
    """
    Run the full load phase: CSV export + optional SQLite export.

    Parameters
    ----------
    tables : dict[str, pd.DataFrame]
        The transformed tables from run_transforms().
    export_sqlite : bool
        If True, also export to SQLite. Defaults to True.

    Returns
    -------
    dict
        Export metadata: {"csv": {...}, "sqlite_path": ... | None}
    """
    logger.info("=" * 50)
    logger.info("Exporting tables to output/")
    logger.info("=" * 50)

    # CSV export
    csv_info = export_to_csv(tables)

    # Totals
    total_rows = sum(info["rows"] for info in csv_info.values())
    total_size = sum(info["size_kb"] for info in csv_info.values())
    logger.info(
        "CSV export complete: %d files, %d total rows, %.1f KB total",
        len(csv_info), total_rows, total_size,
    )

    # Optional SQLite
    sqlite_path = None
    if export_sqlite:
        try:
            sqlite_path = export_to_sqlite(tables)
        except Exception as exc:
            logger.warning("SQLite export failed (non-fatal): %s", exc)

    return {
        "csv": csv_info,
        "sqlite_path": sqlite_path,
    }

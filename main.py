"""
Global Macro Dashboard — Pipeline Entry Point
==============================================
Orchestrates the full ETL pipeline: Extract → Transform → Validate → Load.

Usage:
    python main.py [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD]

Phase 1: Extract raw data from 4 APIs.
Phase 2: Transform raw data into Star Schema DataFrames (3 dims + 5 facts).
Phase 3: Validate data quality (7 assertions).
Phase 4: Load — export 8 CSVs + SQLite to output/.
"""

import argparse
import logging
import os
import sys
import json
from datetime import datetime

import config
from pipeline.extract import (
    extract_fred,
    extract_world_bank,
    extract_imf,
    extract_yfinance,
)
from pipeline.transform import run_transforms
from pipeline.validate import run_validations
from pipeline.load import run_load


def setup_logging():
    """Configure logging to both console and file."""
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # File handler — verbose
    fh = logging.FileHandler(config.LOG_FILE, mode="w", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    root_logger.addHandler(fh)

    # Console handler — info and above
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%H:%M:%S",
    ))
    root_logger.addHandler(ch)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Global Macro Dashboard — ETL Pipeline"
    )
    parser.add_argument(
        "--start-date",
        default=config.START_DATE,
        help="Start date in YYYY-MM-DD format (default: %(default)s)",
    )
    parser.add_argument(
        "--end-date",
        default=config.END_DATE,
        help="End date in YYYY-MM-DD format (default: %(default)s)",
    )
    return parser.parse_args()


def print_summary(fred_data, wb_data, imf_data, yfinance_data):
    """Print a human-readable summary of the extraction results."""
    print("\n" + "=" * 65)
    print("  📊  EXTRACTION SUMMARY")
    print("=" * 65)

    # FRED
    print("\n🇺🇸 FRED (US Economic Data)")
    print("-" * 40)
    for sid, obs in fred_data.items():
        name = config.FRED_SERIES.get(sid, {}).get("name", sid)
        print(f"  {name:<35} {len(obs):>6} observations")
    fred_total = sum(len(v) for v in fred_data.values())
    print(f"  {'TOTAL':<35} {fred_total:>6}")

    # World Bank
    print("\n🌍 World Bank (Global Structural)")
    print("-" * 40)
    for ind, recs in wb_data.items():
        name = config.WB_INDICATORS.get(ind, {}).get("name", ind)
        print(f"  {name:<35} {len(recs):>6} records")
    wb_total = sum(len(v) for v in wb_data.values())
    print(f"  {'TOTAL':<35} {wb_total:>6}")

    # IMF
    print("\n🏛️  IMF (Global Macro Policy)")
    print("-" * 40)
    imf_total = 0
    for ind, countries in imf_data.items():
        name = config.IMF_INDICATORS.get(ind, {}).get("name", ind)
        n_country_series = len(countries)
        imf_total += n_country_series
        print(f"  {name:<35} {n_country_series:>6} country-series")
    print(f"  {'TOTAL':<35} {imf_total:>6}")

    # Yahoo Finance
    print("\n📈 Yahoo Finance (Markets)")
    print("-" * 40)
    yf_total = 0
    for stock, meta in yfinance_data.get("stocks", {}).items():
        count = len(meta.get("candles", []))
        yf_total += count
    for pair, meta in yfinance_data.get("forex", {}).items():
        count = len(meta.get("candles", []))
        yf_total += count
    print(f"  {'TOTAL':<35} {yf_total:>6} candles")

    grand_total = fred_total + wb_total + imf_total + yf_total
    print("\n" + "=" * 65)
    print(f"  ✅  Grand total: {grand_total:,} data points extracted")
    print("=" * 65 + "\n")


def print_transform_summary(tables):
    """Print a human-readable summary of the transform results."""
    print("\n" + "=" * 65)
    print("  🔄  TRANSFORM SUMMARY")
    print("=" * 65)

    dim_tables = {k: v for k, v in tables.items() if k.startswith("dim_")}
    fact_tables = {k: v for k, v in tables.items() if k.startswith("fact_")}

    print("\n📐 Dimension Tables")
    print("-" * 50)
    for name, df in dim_tables.items():
        print(f"  {name:<30} {len(df):>8} rows  ×  {len(df.columns):>2} cols")

    print("\n📊 Fact Tables")
    print("-" * 50)
    for name, df in fact_tables.items():
        if len(df) > 0:
            null_pct = df.isnull().any(axis=1).mean() * 100
            print(f"  {name:<30} {len(df):>8} rows  ×  {len(df.columns):>2} cols  ({null_pct:.1f}% rows w/ nulls)")
        else:
            print(f"  {name:<30} {len(df):>8} rows  ×  {len(df.columns):>2} cols  (empty)")

    total_rows = sum(len(df) for df in tables.values())
    print("\n" + "=" * 65)
    print(f"  ✅  Total: {total_rows:,} rows across {len(tables)} tables")
    print("=" * 65 + "\n")


def print_validation_summary(results):
    """Print a human-readable summary of the validation results."""
    print("\n" + "=" * 65)
    print("  🔍  VALIDATION SUMMARY")
    print("=" * 65)

    for result in results:
        status = "✅" if result.passed else "⚠️ "
        print(f"  {status} {result.check_name}")
        if not result.passed:
            print(f"       {result.message}")
            for detail in result.details:
                print(f"       {detail}")

    passed = sum(1 for r in results if r.passed)
    failed = len(results) - passed
    print("\n" + "-" * 50)
    print(f"  Result: {passed}/{len(results)} passed", end="")
    if failed > 0:
        print(f", {failed} warnings")
    else:
        print(" — all clear!")
    print("=" * 65 + "\n")


def print_load_summary(load_info):
    """Print a human-readable summary of the load/export results."""
    print("\n" + "=" * 65)
    print("  💾  LOAD SUMMARY")
    print("=" * 65)

    csv_info = load_info.get("csv", {})
    print("\n📄 CSV Files")
    print("-" * 50)
    for name, info in csv_info.items():
        print(f"  {name:<30} {info['rows']:>8} rows  ({info['size_kb']:>7.1f} KB)")

    total_rows = sum(info["rows"] for info in csv_info.values())
    total_size = sum(info["size_kb"] for info in csv_info.values())
    print(f"\n  {'TOTAL':<30} {total_rows:>8} rows  ({total_size:>7.1f} KB)")

    if load_info.get("sqlite_path"):
        import os
        db_size = os.path.getsize(load_info["sqlite_path"]) / 1024
        print(f"\n🗄️  SQLite: {load_info['sqlite_path']} ({db_size:.1f} KB)")

    print("=" * 65 + "\n")


def main():

    setup_logging()
    logger = logging.getLogger("main")

    args = parse_args()
    logger.info("Pipeline starting — date range: %s to %s", args.start_date, args.end_date)

    # Update config with CLI overrides
    config.START_DATE = args.start_date
    config.END_DATE = args.end_date

    # ── Phase 1: Extract ──────────────────────────────────────────────
    logger.info("=" * 50)
    logger.info("PHASE 1: EXTRACT")
    logger.info("=" * 50)

    t0 = datetime.now()

    # 1. FRED
    logger.info("── FRED ──")
    fred_data = extract_fred(
        start_date=args.start_date,
        end_date=args.end_date,
    )

    # 2. World Bank
    logger.info("── World Bank ──")
    wb_data = extract_world_bank()

    # 3. IMF
    logger.info("── IMF ──")
    imf_data = extract_imf()

    # 4. Yahoo Finance
    logger.info("── Yahoo Finance ──")
    yfinance_data = extract_yfinance(
        start_date=args.start_date,
        end_date=args.end_date,
    )

    t1 = datetime.now()
    logger.info("Extraction completed in %.1f seconds", (t1 - t0).total_seconds())

    # Print extraction summary
    print_summary(fred_data, wb_data, imf_data, yfinance_data)

    # Save raw extracts for debugging
    raw_output_dir = os.path.join(config.OUTPUT_DIR, "raw")
    os.makedirs(raw_output_dir, exist_ok=True)

    with open(os.path.join(raw_output_dir, "fred_raw.json"), "w") as f:
        json.dump(fred_data, f, indent=2, default=str)
    with open(os.path.join(raw_output_dir, "worldbank_raw.json"), "w") as f:
        json.dump(wb_data, f, indent=2, default=str)
    with open(os.path.join(raw_output_dir, "imf_raw.json"), "w") as f:
        json.dump(imf_data, f, indent=2, default=str)
    with open(os.path.join(raw_output_dir, "yfinance_raw.json"), "w") as f:
        json.dump(yfinance_data, f, indent=2, default=str)

    logger.info("Raw JSON saved to %s", raw_output_dir)

    # ── Phase 2: Transform ────────────────────────────────────────────
    logger.info("=" * 50)
    logger.info("PHASE 2: TRANSFORM")
    logger.info("=" * 50)

    t2 = datetime.now()
    tables = run_transforms(fred_data, wb_data, imf_data, yfinance_data)
    t3 = datetime.now()

    logger.info("Transform completed in %.1f seconds", (t3 - t2).total_seconds())

    # Print transform summary
    print_transform_summary(tables)

    # ── Phase 3: Validate ─────────────────────────────────────────────
    logger.info("=" * 50)
    logger.info("PHASE 3: VALIDATE")
    logger.info("=" * 50)

    t4 = datetime.now()
    validation_results = run_validations(tables)
    t5 = datetime.now()

    logger.info("Validation completed in %.1f seconds", (t5 - t4).total_seconds())

    # Print validation summary
    print_validation_summary(validation_results)

    # ── Phase 4: Load ─────────────────────────────────────────────────
    logger.info("=" * 50)
    logger.info("PHASE 4: LOAD")
    logger.info("=" * 50)

    t6 = datetime.now()
    load_info = run_load(tables, export_sqlite=True)
    t7 = datetime.now()

    logger.info("Load completed in %.1f seconds", (t7 - t6).total_seconds())

    # Print load summary
    print_load_summary(load_info)

    # ── Pipeline Complete ─────────────────────────────────────────────
    total_elapsed = (t7 - t0).total_seconds()
    logger.info("Pipeline finished in %.1f seconds total", total_elapsed)

    passed = sum(1 for r in validation_results if r.passed)
    failed = len(validation_results) - passed
    total_rows = sum(info["rows"] for info in load_info["csv"].values())
    total_files = len(load_info["csv"]) + (1 if load_info.get("sqlite_path") else 0)

    print("\n" + "=" * 65)
    print("  🏁  PIPELINE COMPLETE")
    print("=" * 65)
    print(f"  ⏱️   Duration:     {total_elapsed:.1f} seconds")
    print(f"  📊  Tables:       {len(load_info['csv'])} CSVs" + (" + 1 SQLite" if load_info.get('sqlite_path') else ""))
    print(f"  📏  Total rows:   {total_rows:,}")
    print(f"  ✅  Validation:   {passed}/{len(validation_results)} checks passed")
    if failed > 0:
        print(f"  ⚠️   Warnings:     {failed} check(s) failed — see output/validation_report.txt")
    print(f"  📂  Output dir:   {config.OUTPUT_DIR}")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()

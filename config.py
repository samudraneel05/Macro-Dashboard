"""
Global Macro Dashboard — Configuration
=======================================
Central config for date ranges, series IDs, country lists,
and all constants used across the ETL pipeline.
"""

import os
from datetime import datetime


# ---------------------------------------------------------------------------
# Date Ranges
# ---------------------------------------------------------------------------
START_DATE = "2015-01-01"
END_DATE = datetime.now().strftime("%Y-%m-%d")
CURRENT_YEAR = datetime.now().year

# World Bank date range format (years only)
WB_DATE_RANGE = f"2015:{datetime.now().year}"

# ---------------------------------------------------------------------------
# FRED — US Economic Deep Dive
# ---------------------------------------------------------------------------

FRED_SERIES = {
    "CPIAUCSL": {
        "name": "Consumer Price Index (CPI)",
        "unit": "Index (1982=100)",
        "frequency": "Monthly",
    },
    "FEDFUNDS": {
        "name": "Federal Funds Rate",
        "unit": "Percent",
        "frequency": "Monthly",
    },
    "GDPC1": {
        "name": "US GDP (Real)",
        "unit": "Billions USD",
        "frequency": "Quarterly",
    },
    "GS10": {
        "name": "10-Year Treasury Yield",
        "unit": "Percent",
        "frequency": "Monthly",
    },
    "UNRATE": {
        "name": "Unemployment Rate",
        "unit": "Percent",
        "frequency": "Monthly",
    },
    "BOPGSTB": {
        "name": "US Trade Balance",
        "unit": "Millions USD",
        "frequency": "Monthly",
    },
}

FRED_SERIES_IDS = list(FRED_SERIES.keys())

# ---------------------------------------------------------------------------
# World Bank — Global Structural Data
# ---------------------------------------------------------------------------
WB_BASE_URL = "https://api.worldbank.org/v2/country"

WB_INDICATORS = {
    "NY.GDP.MKTP.CD": {
        "name": "GDP (current US$)",
        "unit": "Current USD",
        "frequency": "Annual",
    },
    "SP.POP.TOTL": {
        "name": "Population",
        "unit": "Count",
        "frequency": "Annual",
    },
    "NY.GNP.PCAP.CD": {
        "name": "GNI Per Capita",
        "unit": "Current USD",
        "frequency": "Annual",
    },
    "SL.UEM.TOTL.ZS": {
        "name": "Unemployment Rate",
        "unit": "Percent",
        "frequency": "Annual",
    },
    "NY.GDP.MKTP.KD.ZG": {
        "name": "GDP Growth (annual %)",
        "unit": "Percent",
        "frequency": "Annual",
    },
    "FP.CPI.TOTL.ZG": {
        "name": "Inflation (CPI, annual %)",
        "unit": "Percent",
        "frequency": "Annual",
    },
    "GC.DOD.TOTL.GD.ZS": {
        "name": "Government Debt-to-GDP",
        "unit": "Percent of GDP",
        "frequency": "Annual",
    },
    "BN.CAB.XOKA.GD.ZS": {
        "name": "Current Account Balance",
        "unit": "Percent of GDP",
        "frequency": "Annual",
    },
    "GC.REV.XGRT.GD.ZS": {
        "name": "Government Revenue",
        "unit": "Percent of GDP",
        "frequency": "Annual",
    },
}

WB_INDICATOR_CODES = list(WB_INDICATORS.keys())

# G20 country codes (ISO Alpha-3), semicolon-separated for WB URL
WB_COUNTRY_CODES = "ARG;AUS;BRA;CAN;CHN;FRA;DEU;IND;IDN;ITA;JPN;MEX;RUS;SAU;ZAF;KOR;TUR;GBR;USA"

# ---------------------------------------------------------------------------
# IMF — Global Macro Policy Data
# ---------------------------------------------------------------------------
# WEO-based fiscal & monetary policy metrics for G20 nations.
# Complements World Bank by providing the "how healthy" metrics (growth,
# inflation, debt). WEO updates only twice a year (April & October), so
# caching is essential — the pipeline caches via raw JSON + SQLite.

IMF_BASE_URL = "https://www.imf.org/external/datamapper/api/v2"

IMF_INDICATORS = {
    "NGDP_RPCH": {
        "name": "GDP Growth (annual %)",
        "unit": "Percent",
        "frequency": "Annual",
    },
    "PCPIPCH": {
        "name": "Inflation (CPI, annual %)",
        "unit": "Percent",
        "frequency": "Annual",
    },
    "GGXWDG_NGDP": {
        "name": "Government Debt-to-GDP",
        "unit": "Percent of GDP",
        "frequency": "Annual",
    },
    "BCA_NGDPD": {
        "name": "Current Account Balance",
        "unit": "Percent of GDP",
        "frequency": "Annual",
    },
    "rev": {
        "name": "Government Revenue",
        "unit": "Percent of GDP",
        "frequency": "Annual",
    },
}

IMF_INDICATOR_CODES = list(IMF_INDICATORS.keys())

# G20 country codes (ISO Alpha-3), slash-separated for the IMF URL path.
# Must match the World Bank / COUNTRY_LOOKUP set so joins work.
IMF_COUNTRY_CODES = [
    "USA", "CHN", "JPN", "DEU", "IND", "GBR", "FRA", "ITA", "CAN", "BRA",
    "RUS", "ZAF", "TUR", "SAU", "MEX", "ARG", "AUS", "KOR", "IDN",
]

IMF_SLEEP = 2.0  # seconds between IMF requests (conservative; avoids IP blocking)

# ---------------------------------------------------------------------------
# Yahoo Finance — Global Markets (Real-Time)
# ---------------------------------------------------------------------------
# Daily OHLCV data via the yfinance library (no API key required).

YFINANCE_STOCK_SYMBOLS = {
    "^GSPC":  {"display_name": "S&P 500",    "type": "stock"},
    "^NDX":   {"display_name": "NASDAQ 100", "type": "stock"},
    "^FTSE":  {"display_name": "FTSE 100",   "type": "stock"},
    "^GDAXI": {"display_name": "DAX",        "type": "stock"},
    "^N225":  {"display_name": "Nikkei 225", "type": "stock"},
}

YFINANCE_FOREX_SYMBOLS = {
    "EURUSD=X": {"display_name": "EUR/USD", "pair": "EUR/USD", "type": "forex"},
    "GBPUSD=X": {"display_name": "GBP/USD", "pair": "GBP/USD", "type": "forex"},
    "JPY=X":    {"display_name": "USD/JPY", "pair": "USD/JPY", "type": "forex"},
}

# ---------------------------------------------------------------------------
# Change-Type Classification (Level vs. Rate Series)
# ---------------------------------------------------------------------------
# Controls how YoY / period-over-period changes are calculated in transform.py:
#
#   Level series (GDP in USD, CPI index, population, stock prices):
#       YoY = percentage change = (current / prior - 1) × 100
#
#   Rate series (inflation %, interest rates %, unemployment %, debt-to-GDP %):
#       YoY = absolute difference in percentage points = current - prior
#
# Series NOT listed below default to level (percentage change).

FRED_RATE_SERIES = {"FEDFUNDS", "GS10", "UNRATE"}

WB_RATE_INDICATORS = {
    "SL.UEM.TOTL.ZS",       # Unemployment Rate (%)
    "NY.GDP.MKTP.KD.ZG",    # GDP Growth (annual %)
    "FP.CPI.TOTL.ZG",       # Inflation (CPI, annual %)
    "GC.DOD.TOTL.GD.ZS",    # Government Debt-to-GDP (% of GDP)
    "BN.CAB.XOKA.GD.ZS",    # Current Account Balance (% of GDP)
    "GC.REV.XGRT.GD.ZS",    # Government Revenue (% of GDP)
}

IMF_RATE_INDICATORS = {
    "NGDP_RPCH",     # GDP Growth (annual %)
    "PCPIPCH",       # Inflation (CPI, annual %)
    "GGXWDG_NGDP",   # Government Debt-to-GDP (% of GDP)
    "BCA_NGDPD",     # Current Account Balance (% of GDP)
    "rev",           # Government Revenue (% of GDP)
}

# ---------------------------------------------------------------------------
# Country Dimension Lookup
# ---------------------------------------------------------------------------
COUNTRY_LOOKUP = {
    "ARG": {"name": "Argentina",     "region": "South America"},
    "AUS": {"name": "Australia",     "region": "Oceania"},
    "BRA": {"name": "Brazil",        "region": "South America"},
    "CAN": {"name": "Canada",        "region": "North America"},
    "CHN": {"name": "China",         "region": "Asia"},
    "FRA": {"name": "France",        "region": "Europe"},
    "DEU": {"name": "Germany",       "region": "Europe"},
    "IND": {"name": "India",         "region": "Asia"},
    "IDN": {"name": "Indonesia",     "region": "Asia"},
    "ITA": {"name": "Italy",         "region": "Europe"},
    "JPN": {"name": "Japan",         "region": "Asia"},
    "MEX": {"name": "Mexico",        "region": "North America"},
    "RUS": {"name": "Russia",        "region": "Europe"},
    "SAU": {"name": "Saudi Arabia",  "region": "Middle East"},
    "ZAF": {"name": "South Africa",  "region": "Africa"},
    "KOR": {"name": "South Korea",   "region": "Asia"},
    "TUR": {"name": "Turkey",        "region": "Europe"},
    "GBR": {"name": "United Kingdom","region": "Europe"},
    "USA": {"name": "United States", "region": "North America"},
}

# ---------------------------------------------------------------------------
# Logging & Output
# ---------------------------------------------------------------------------
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
LOG_FILE = os.path.join(OUTPUT_DIR, "pipeline.log")

# ---------------------------------------------------------------------------
# HTTP / Rate Limiting
# ---------------------------------------------------------------------------
REQUEST_TIMEOUT = 30          # seconds
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2        # exponential backoff: 2s, 4s, 8s

FRED_SLEEP = 0.5              # seconds between FRED requests
WB_SLEEP = 0.5                # seconds between World Bank requests

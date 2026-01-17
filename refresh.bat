@echo off
REM =============================================================================
REM refresh.bat - one-command data refresh (Windows)
REM =============================================================================
REM Re-runs the full ETL pipeline to refresh output\dashboard.db and the CSVs.
REM After this completes, open Power BI Desktop and click "Refresh" - the
REM Python script source will read the updated dashboard.db.
REM
REM Usage:
REM   refresh.bat
REM   refresh.bat --start-date 2020-01-01
REM   refresh.bat --start-date 2020-01-01 --end-date 2025-12-31
REM
REM Requirements:
REM   - Python 3.9+ on PATH (or a .venv in this folder, auto-activated below).
REM   - pip install -r requirements.txt run once.
REM =============================================================================
setlocal enabledelayedexpansion

cd /d "%~dp0"

REM Activate the project venv if it exists, otherwise use PATH python.
set "PYTHON=python"
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
    set "PYTHON=python"
)

echo ================================================================
echo   Refreshing Global Macro Dashboard data
echo   %DATE% %TIME%
echo ================================================================

%PYTHON% main.py %*
if errorlevel 1 (
    echo.
    echo ================================================================
    echo   ERROR: pipeline failed. See output\pipeline.log
    echo ================================================================
    exit /b 1
)

echo.
echo ================================================================
echo   Refresh complete.
echo   Cached data: %CD%\output\dashboard.db
echo.
echo   Next step:
echo     1. Open your .pbix in Power BI Desktop.
echo     2. Click Home ^> Refresh ^(uses the cached dashboard.db^).
echo.
echo   For a live pull inside Power BI without running this script,
echo   set the Windows env var POWERBI_FRESH=1 then click Refresh.
echo ================================================================
endlocal

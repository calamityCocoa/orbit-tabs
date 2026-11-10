@echo off
cd /d "%~dp0"
where py >nul 2>&1
if errorlevel 1 (
    echo Install Python 3.10 or later from https://www.python.org/downloads/windows/
    pause
    exit /b 1
)
py -3 -c "from PySide6.QtWebEngineWidgets import QWebEngineView" >nul 2>&1
if errorlevel 1 (
    py -3 -m pip install -r requirements.txt
    if errorlevel 1 (
        pause
        exit /b 1
    )
)
where pyw >nul 2>&1
if errorlevel 1 (
    py -3 orbit_embedded.py
) else (
    start "" pyw -3 "%~dp0orbit_embedded.py"
)

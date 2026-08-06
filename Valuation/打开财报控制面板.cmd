@echo off
setlocal

cd /d "%~dp0"

set "URL=http://127.0.0.1:8010"
set "VALUATION_DASHBOARD_PORT=8010"
set "BUNDLED_PYTHON=C:\Users\Admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if exist "%BUNDLED_PYTHON%" (
  set "PYTHON_CMD=%BUNDLED_PYTHON%"
) else (
  where python >nul 2>nul
  if %errorlevel%==0 (
    set "PYTHON_CMD=python"
  ) else (
    where py >nul 2>nul
    if %errorlevel%==0 (
      set "PYTHON_CMD=py -3"
    )
  )
)

if not defined PYTHON_CMD (
  echo Could not find Python.
  echo Please install Python or run the dashboard from Codex.
  pause
  exit /b 1
)

echo Starting Financial Report Dashboard...
echo URL: %URL%
echo.
echo If the page does not open automatically, copy this URL into your browser:
echo %URL%
echo.

start "" "%URL%"
%PYTHON_CMD% app.py

endlocal




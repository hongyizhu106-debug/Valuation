@echo off
setlocal

cd /d "%~dp0"

set "URL=http://127.0.0.1:8010"
set "VALUATION_DASHBOARD_PORT=8010"
set "BUNDLED_PYTHON=C:\Users\Admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
set "PYTHON_EXE="
set "PYTHON_ARGS="

if exist "%BUNDLED_PYTHON%" (
  set "PYTHON_EXE=%BUNDLED_PYTHON%"
) else (
  where python >nul 2>nul
  if %errorlevel%==0 (
    set "PYTHON_EXE=python"
  ) else (
    where py >nul 2>nul
    if %errorlevel%==0 (
      set "PYTHON_EXE=py"
      set "PYTHON_ARGS=-3"
    )
  )
)

if not defined PYTHON_EXE (
  echo Could not find Python.
  echo Please install Python first.
  pause
  exit /b 1
)

echo Starting Financial Report Dashboard...
echo Server window will stay open while the website is running.
echo Opening browser: %URL%
echo.

start "Valuation Dashboard Server" /D "%~dp0" cmd /k ""%PYTHON_EXE%" %PYTHON_ARGS% app.py"
timeout /t 2 /nobreak >nul
start "" "%URL%"

endlocal




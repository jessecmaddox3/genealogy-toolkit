@echo off
cd /d "%~dp0"
py -3 -c "import sys; sys.exit(not (sys.version_info >= (3, 12)))" >nul 2>&1
if not errorlevel 1 (
  py -3 start_demo.py %*
  if errorlevel 1 pause
  exit /b
)
python -c "import sys; sys.exit(not (sys.version_info >= (3, 12)))" >nul 2>&1
if not errorlevel 1 (
  python start_demo.py %*
  if errorlevel 1 pause
  exit /b
)
echo Install Python 3.12 or newer from https://www.python.org/downloads/, then try again.
pause
exit /b 2

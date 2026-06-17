@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

rem Ensure cargo is reachable even if PATH was not refreshed after install.
set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"

where npm >nul 2>nul || (
  echo [ERROR] Node.js/npm was not found. Install it from https://nodejs.org.
  pause
  exit /b 1
)

where cargo >nul 2>nul || (
  echo [ERROR] Rust/Cargo was not found. Install it from https://www.rust-lang.org/tools/install.
  pause
  exit /b 1
)

if not exist "apps\desktop\node_modules" (
  echo First setup: running npm install for desktop...
  pushd "apps\desktop"
  call npm install || (
    popd
    echo [ERROR] npm install failed.
    pause
    exit /b 1
  )
  popd
)

if not exist "recovery\.venv\Scripts\python.exe" (
  echo First setup: creating Python sidecar environment...
  python -m venv "recovery\.venv" || (
    echo [ERROR] Failed to create Python virtual environment.
    pause
    exit /b 1
  )
)

echo Checking Python sidecar dependencies...
"%~dp0recovery\.venv\Scripts\python.exe" -c "import fitz, pdf_splitter_tool" >nul 2>nul
if errorlevel 1 (
  echo Installing Python sidecar dependencies...
  "%~dp0recovery\.venv\Scripts\python.exe" -m pip install -e "%~dp0recovery" || (
    echo [ERROR] Failed to install Python sidecar dependencies.
    pause
    exit /b 1
  )
)

rem Use the bundled recovery venv as the PDF sidecar Python (no py launcher needed).
set "PDF_ORGANIZER_PYTHON=%~dp0recovery\.venv\Scripts\python.exe"
set "PDF_ORGANIZER_RECOVERY_DIR=%~dp0recovery"

if "%~1"=="--setup-only" (
  echo Setup check completed.
  exit /b 0
)

echo Starting PDF tool (dev). First build may take a few minutes...
echo A desktop window will open when the build finishes.
echo.
cd /d "%~dp0apps\desktop"
call npm run tauri dev

echo.
echo === Dev server stopped. Press any key to close this window. ===
pause >nul

@echo off
setlocal
cd /d "%~dp0apps\desktop"

rem Ensure cargo is reachable even if PATH was not refreshed after install.
set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"

rem Use the bundled recovery venv as the PDF sidecar Python (no py launcher needed).
set "PDF_ORGANIZER_PYTHON=%~dp0recovery\.venv\Scripts\python.exe"
set "PDF_ORGANIZER_RECOVERY_DIR=%~dp0recovery"

echo Starting PDF tool (dev). First build may take a few minutes...
echo A desktop window will open when the build finishes.
echo.
call npm run tauri dev

echo.
echo === Dev server stopped. Press any key to close this window. ===
pause >nul

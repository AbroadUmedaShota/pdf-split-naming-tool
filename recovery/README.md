# PDF Split Naming Tool Recovery

This is the maintainable recovery implementation for `PDF分割命名ツール_v3_1_1`.

## Run

```powershell
cd recovery
python -m pdf_splitter_tool
```

## Test

```powershell
cd recovery
python -m pytest
python scripts\gui_smoke.py
```

## Verified behavior

- Step 3 input assistance refreshes OCR-derived candidates, selects the first candidate, shows candidate count and selected value, and focuses the candidate list.
- The selected candidate can be copied with the copy button, Enter, Ctrl+C, or double-click. Escape clears the selection and disables copying.
- `tests/test_app_shortcuts.py` covers the shared shortcut/status text, and `scripts/gui_smoke.py` covers the GUI focus, copy, and clear behavior.

## Build distribution

```powershell
cd recovery
python -m pip install -e ".[test,build]"
.\scripts\build_distribution.ps1 -VersionName pdf-split-naming-tool-recovery-YYYYMMDD
```

The build creates a PyInstaller one-folder app under `recovery/dist/<VersionName>/`
and a ZIP at `recovery/dist/<VersionName>.zip`. Existing distribution folders or
ZIP files are not overwritten.

For packaged EXE runs, `presets.json` and `_pdf_split_state.json` are stored in
the same folder as the EXE. Use `--smoke` to verify runtime paths without
opening the GUI:

```powershell
.\dist\<VersionName>\<VersionName>.exe --smoke --smoke-output .\dist\<VersionName>\smoke-result.json
```

See `docs/2026-05-19_配布前チェックリスト.md` before copying a build to a shared folder.

The latest Step 3 input-assist copy UX changes are verified in development, but no new distribution ZIP has been built for them yet.

## Current priority

- ヨシダエルシス preset first.
- Preset-based fields, naming rules, and extraction keywords.
- Step 2 keyboard focus behavior.
- Responsive preview and thumbnail handling for 200-250+ page PDFs.

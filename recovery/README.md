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
```

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

## Current priority

- ヨシダエルシス preset first.
- Preset-based fields, naming rules, and extraction keywords.
- Step 2 keyboard focus behavior.
- Responsive preview and thumbnail handling for 200-250+ page PDFs.

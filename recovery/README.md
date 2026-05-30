# PDF Split Naming Tool Sidecar

This package is the Python sidecar for the desktop app in `../apps/desktop`.
It is not a second user-facing GUI app.

The sidecar owns PDF-specific processing such as page counts, previews,
split/export, filename generation, preflight checks, and persisted work state.

## Smoke

```powershell
cd recovery
python -m pdf_splitter_tool --smoke
```

## Test

```powershell
cd recovery
python -m pytest
```

## Sidecar request

```powershell
cd recovery
python -m pdf_splitter_tool --sidecar-request request.json --sidecar-output response.json
```

## Build distribution

The current user-facing distribution target is the Tauri desktop app under
`../apps/desktop`. The legacy PyInstaller build script remains as historical
recovery material and should be revisited before being used for a new release.

```powershell
cd recovery
python -m pip install -e ".[test,build]"
.\scripts\build_distribution.ps1 -VersionName pdf-split-naming-tool-recovery-YYYYMMDD
```

The build creates a PyInstaller one-folder app under `recovery/dist/<VersionName>/`
and a ZIP at `recovery/dist/<VersionName>.zip`. Existing distribution folders or
ZIP files are not overwritten.

For packaged sidecar runs, `_pdf_split_state.json` and related state files are
stored in the configured app work folder. Use `--smoke` to verify runtime paths
without processing a PDF:

```powershell
.\dist\<VersionName>\<VersionName>.exe --smoke --smoke-output .\dist\<VersionName>\smoke-result.json
```

See `../docs/2026-05-19_配布前チェックリスト.md` before copying a build to a shared folder.

## Current priority

- Keep the sidecar command contract small and stable for `apps/desktop`.
- Verify the MVP flow with real PDFs.
- Defer OCR, presets, history, and advanced page organization until MVP use is confirmed.

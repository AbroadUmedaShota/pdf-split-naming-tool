param(
    [Parameter(Mandatory = $true)]
    [string]$PdfPath,

    [string]$OutputRoot
)

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$RecoveryPath = Join-Path $RepoRoot "recovery"

if (-not (Test-Path -LiteralPath $RecoveryPath -PathType Container)) {
    Write-Error "Recovery directory not found: $RecoveryPath"
    exit 1
}

$ResolvedPdfPath = (Resolve-Path -LiteralPath $PdfPath).Path
if (-not (Test-Path -LiteralPath $ResolvedPdfPath -PathType Leaf)) {
    Write-Error "PDF file not found: $PdfPath"
    exit 1
}

if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $OutputRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("pdf-split-smoke-" + [System.Guid]::NewGuid().ToString("N"))
}

$OutputRootFullPath = [System.IO.Path]::GetFullPath($OutputRoot)
New-Item -ItemType Directory -Force -Path $OutputRootFullPath | Out-Null

$PreviousPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = $RecoveryPath

$PythonScript = @'
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from pdf_splitter_tool.sidecar import handle_request


def compact_response(response: dict[str, Any]) -> dict[str, Any]:
    compact = {key: value for key, value in response.items() if key != "image_data_url"}
    image_data_url = response.get("image_data_url")
    if isinstance(image_data_url, str):
        compact["image_data_url_prefix"] = image_data_url[:22]
        compact["image_data_url_length"] = len(image_data_url)
    return compact


def response_ok(response: dict[str, Any]) -> bool:
    return response.get("ok") is True


def main() -> int:
    pdf_path = Path(sys.argv[1]).resolve()
    output_root = Path(sys.argv[2]).resolve()
    export_dir = output_root / "export"
    work_dir = output_root / "work"
    export_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    failures: list[str] = []

    info = handle_request({"command": "pdf_info", "pdf_path": str(pdf_path)})
    if not response_ok(info):
        failures.append("pdf_info")

    page_count = int(info.get("page_count", 0) or 0) if response_ok(info) else 0
    first_preview = handle_request({"command": "page_preview", "pdf_path": str(pdf_path), "page_no": 1})
    if not response_ok(first_preview):
        failures.append("page_preview:first")

    final_page_no = page_count if page_count > 0 else 1
    final_preview = handle_request({"command": "page_preview", "pdf_path": str(pdf_path), "page_no": final_page_no})
    if not response_ok(final_preview):
        failures.append("page_preview:final")

    segment = {
        "pdf_path": str(pdf_path),
        "start_page": 1,
        "end_page": 1,
        "metadata": {"box_no": "1", "binder_no": "1", "seq": "1"},
    }
    segments = [segment]

    preflight = handle_request({"command": "preflight", "output_dir": str(export_dir), "segments": segments})
    if not (response_ok(preflight) and preflight.get("can_run") is True):
        failures.append("preflight")

    export = handle_request({"command": "export", "output_dir": str(export_dir), "segments": segments})
    export_summary = export.get("summary") if isinstance(export.get("summary"), dict) else {}
    if not (
        response_ok(export)
        and export_summary.get("created") == 1
        and export_summary.get("failed") == 0
    ):
        failures.append("export")

    state_payload = {
        "version": 1,
        "input_paths": [str(pdf_path)],
        "current_page": 1,
        "output_dir": str(export_dir),
        "segments": segments,
    }
    state_save = handle_request({"command": "state_save", "work_dir": str(work_dir), "state": state_payload})
    if not response_ok(state_save):
        failures.append("state_save")

    state_load = handle_request({"command": "state_load", "work_dir": str(work_dir)})
    state_roundtrip = response_ok(state_load) and state_load.get("state") == state_payload
    if not response_ok(state_load):
        failures.append("state_load")
    if not state_roundtrip:
        failures.append("state_roundtrip")

    export_items = export.get("items", []) if isinstance(export.get("items"), list) else []
    exported_paths = [
        str(item.get("output_path", ""))
        for item in export_items
        if isinstance(item, dict) and item.get("output_path")
    ]

    summary = {
        "ok": not failures,
        "pdf_path": str(pdf_path),
        "output_root": str(output_root),
        "page_count": page_count,
        "preview": {
            "first": {
                "ok": response_ok(first_preview),
                "page_no": first_preview.get("page_no"),
                "image_data_url_length": len(first_preview.get("image_data_url", ""))
                if isinstance(first_preview.get("image_data_url"), str)
                else 0,
            },
            "final": {
                "ok": response_ok(final_preview),
                "page_no": final_preview.get("page_no"),
                "image_data_url_length": len(final_preview.get("image_data_url", ""))
                if isinstance(final_preview.get("image_data_url"), str)
                else 0,
            },
        },
        "preflight": {
            "ok": response_ok(preflight),
            "can_run": preflight.get("can_run"),
            "checks": preflight.get("checks", []),
            "messages": preflight.get("messages", []),
        },
        "export": {
            "ok": response_ok(export),
            "summary": export_summary,
            "output_dir": str(export_dir),
            "output_paths": exported_paths,
            "items": export_items,
        },
        "state_roundtrip": {
            "ok": state_roundtrip,
            "work_dir": str(work_dir),
            "save": compact_response(state_save),
            "load": {
                "ok": response_ok(state_load),
                "messages": state_load.get("messages", []),
                "missing_input_paths": state_load.get("missing_input_paths", []),
            },
        },
        "failures": failures,
    }

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
'@

try {
    $PythonScript | python - $ResolvedPdfPath $OutputRootFullPath
    exit $LASTEXITCODE
}
finally {
    if ($null -eq $PreviousPythonPath) {
        Remove-Item Env:\PYTHONPATH -ErrorAction SilentlyContinue
    }
    else {
        $env:PYTHONPATH = $PreviousPythonPath
    }
}

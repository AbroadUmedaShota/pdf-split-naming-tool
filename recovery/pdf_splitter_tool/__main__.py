from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pdf_splitter_tool.app import default_work_dir, main
from pdf_splitter_tool.app_metadata import APP_ID, APP_NAME, __version__
from pdf_splitter_tool.sidecar import handle_request
from pdf_splitter_tool.state import STATE_BAK_FILENAME, STATE_FILENAME, STATE_TMP_FILENAME


def sidecar_error_response(exc: Exception) -> str:
    return json.dumps(
        {
            "ok": False,
            "command": "",
            "error": str(exc),
            "error_type": type(exc).__name__,
        },
        ensure_ascii=False,
        indent=2,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true", help="Print runtime paths and exit without opening the GUI.")
    parser.add_argument("--smoke-output", help="Write --smoke JSON to this file. Useful for windowed EXE checks.")
    parser.add_argument("--sidecar-request", help="Read a sidecar JSON request from this file, or '-' for stdin.")
    parser.add_argument("--sidecar-output", help="Write sidecar JSON response to this file instead of stdout.")
    args = parser.parse_args()
    if args.sidecar_request:
        try:
            request_text = (
                sys.stdin.read()
                if args.sidecar_request == "-"
                else Path(args.sidecar_request).read_text(encoding="utf-8")
            )
            response = json.dumps(handle_request(json.loads(request_text)), ensure_ascii=False, indent=2)
        except Exception as exc:
            response = sidecar_error_response(exc)
        if args.sidecar_output:
            Path(args.sidecar_output).write_text(response, encoding="utf-8")
        else:
            print(response)
    elif args.smoke:
        work_dir = default_work_dir()
        payload = json.dumps(
            {
                "app_id": APP_ID,
                "app_name": APP_NAME,
                "version": __version__,
                "work_dir": str(work_dir),
                "presets_path": str(work_dir / "presets.json"),
                "state_path": str(work_dir / STATE_FILENAME),
                "state_backup_path": str(work_dir / STATE_BAK_FILENAME),
                "state_tmp_path": str(work_dir / STATE_TMP_FILENAME),
            },
            ensure_ascii=False,
            indent=2,
        )
        if args.smoke_output:
            Path(args.smoke_output).write_text(payload, encoding="utf-8")
        else:
            print(payload)
    else:
        main()

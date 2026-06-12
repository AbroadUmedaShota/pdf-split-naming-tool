from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pdf_splitter_tool.app_metadata import APP_ID, APP_NAME, __version__
from pdf_splitter_tool.runtime import default_work_dir
from pdf_splitter_tool.sidecar import handle_request, serve
from pdf_splitter_tool.state import STATE_BAK_FILENAME, STATE_FILENAME, STATE_TMP_PREFIX, STATE_TMP_SUFFIX


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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true", help="Print runtime paths and exit.")
    parser.add_argument("--smoke-output", help="Write --smoke JSON to this file.")
    parser.add_argument("--sidecar-request", help="Read a sidecar JSON request from this file, or '-' for stdin.")
    parser.add_argument("--sidecar-output", help="Write sidecar JSON response to this file instead of stdout.")
    parser.add_argument("--sidecar-serve", action="store_true", help="Run in resident serve mode: JSON Lines loop on stdin/stdout.")
    args = parser.parse_args()
    if args.sidecar_request:
        try:
            request_text = (
                sys.stdin.read()
                if args.sidecar_request == "-"
                else Path(args.sidecar_request).read_text(encoding="utf-8")
            )
            response = json.dumps(
                handle_request(json.loads(request_text)),
                ensure_ascii=False,
                separators=(",", ":"),
            )
        except Exception as exc:
            response = sidecar_error_response(exc)
        if args.sidecar_output:
            Path(args.sidecar_output).write_text(response, encoding="utf-8")
        else:
            print(response)
        return
    if args.sidecar_serve:
        # Reconfigure stdout/stdin for binary-safe UTF-8 with LF line endings.
        # This prevents Windows CRLF conversion from corrupting the JSON Lines stream.
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")  # type: ignore[union-attr]
        sys.stdin.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        serve(sys.stdin, sys.stdout)
        return
    if args.smoke:
        work_dir = default_work_dir()
        payload = json.dumps(
            {
                "app_id": APP_ID,
                "app_name": APP_NAME,
                "version": __version__,
                "work_dir": str(work_dir),
                "state_path": str(work_dir / STATE_FILENAME),
                "state_backup_path": str(work_dir / STATE_BAK_FILENAME),
                "state_tmp_path": str(work_dir / f"{STATE_TMP_PREFIX}<pid>{STATE_TMP_SUFFIX}"),
            },
            ensure_ascii=False,
            indent=2,
        )
        if args.smoke_output:
            Path(args.smoke_output).write_text(payload, encoding="utf-8")
        else:
            print(payload)
        return
    parser.print_help()


if __name__ == "__main__":
    main()

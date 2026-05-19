from __future__ import annotations

import argparse
import json

from pdf_splitter_tool.app import default_work_dir, main
from pdf_splitter_tool.app_metadata import APP_ID, APP_NAME, __version__
from pdf_splitter_tool.state import STATE_BAK_FILENAME, STATE_FILENAME, STATE_TMP_FILENAME


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true", help="Print runtime paths and exit without opening the GUI.")
    parser.add_argument("--smoke-output", help="Write --smoke JSON to this file. Useful for windowed EXE checks.")
    args = parser.parse_args()
    if args.smoke:
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
            from pathlib import Path

            Path(args.smoke_output).write_text(payload, encoding="utf-8")
        else:
            print(payload)
    else:
        main()

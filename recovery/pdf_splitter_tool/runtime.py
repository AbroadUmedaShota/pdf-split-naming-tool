from __future__ import annotations

import os
from pathlib import Path

WORK_DIR_NAME = "PDF整理ツール"


def default_work_dir() -> Path:
    override = os.environ.get("PDF_ORGANIZER_WORK_DIR", "").strip()
    if override:
        return Path(override)
    appdata = os.environ.get("APPDATA", "").strip()
    if appdata:
        return Path(appdata) / WORK_DIR_NAME
    return Path.home() / ".pdf_split_naming_tool"


def work_dir_from_request(request: dict[str, object]) -> Path:
    raw = str(request.get("work_dir", "")).strip()
    return Path(raw) if raw else default_work_dir()

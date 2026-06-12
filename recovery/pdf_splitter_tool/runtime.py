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
    if not raw:
        return default_work_dir()
    # Reject UNC paths (\\server\share or //server/share) for the state storage
    # directory.  Network paths are unreliable for atomic file operations and can
    # cause the state manager to hang or silently corrupt saves.
    if raw.startswith("\\\\") or raw.startswith("//"):
        raise ValueError(
            "状態保存先にネットワークパスは指定できません。ローカルフォルダを指定してください。"
            f" (受け取った値: {raw!r})"
        )
    return Path(raw).resolve()

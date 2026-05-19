from __future__ import annotations

import json
from pathlib import Path
from typing import Any


STATE_FILENAME = "_pdf_split_state.json"
STATE_BAK_FILENAME = "_pdf_split_state.bak.json"
STATE_TMP_FILENAME = "_pdf_split_state.tmp"


class StateManager:
    def __init__(self, work_dir: Path) -> None:
        self.work_dir = work_dir
        self.state_path = work_dir / STATE_FILENAME
        self.backup_path = work_dir / STATE_BAK_FILENAME
        self.tmp_path = work_dir / STATE_TMP_FILENAME

    def load(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {}
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def save(self, state: dict[str, Any]) -> None:
        self.work_dir.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(state, ensure_ascii=False, indent=2)
        self.tmp_path.write_text(payload, encoding="utf-8")
        json.loads(self.tmp_path.read_text(encoding="utf-8"))
        if self.state_path.exists():
            self.state_path.replace(self.backup_path)
        self.tmp_path.replace(self.state_path)

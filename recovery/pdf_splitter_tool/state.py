from __future__ import annotations

import json
from pathlib import Path
from typing import Any


STATE_FILENAME = "_pdf_split_state.json"
STATE_BAK_FILENAME = "_pdf_split_state.bak.json"
STATE_TMP_FILENAME = "_pdf_split_state.tmp"


class StateFormatError(ValueError):
    pass


class StateManager:
    def __init__(self, work_dir: Path) -> None:
        self.work_dir = work_dir
        self.state_path = work_dir / STATE_FILENAME
        self.backup_path = work_dir / STATE_BAK_FILENAME
        self.tmp_path = work_dir / STATE_TMP_FILENAME

    def load(self) -> dict[str, Any]:
        if not self.state_path.exists():
            if self.backup_path.exists():
                try:
                    payload = self._load_file(self.backup_path)
                    self._restore_loaded_payload(payload)
                    return payload
                except Exception:
                    self._archive_corrupt_file(self.backup_path)
            return self._load_tmp_or_empty()
        try:
            return self._load_file(self.state_path)
        except Exception:
            self._archive_corrupt_file(self.state_path)
            if self.backup_path.exists():
                try:
                    payload = self._load_file(self.backup_path)
                    self._restore_loaded_payload(payload)
                    return payload
                except Exception:
                    self._archive_corrupt_file(self.backup_path)
            return self._load_tmp_or_empty()

    def _restore_loaded_payload(self, payload: dict[str, Any]) -> None:
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_tmp_or_empty(self) -> dict[str, Any]:
        if self.tmp_path.exists():
            try:
                payload = self._load_file(self.tmp_path)
                self.tmp_path.replace(self.state_path)
                return payload
            except Exception:
                self._archive_corrupt_file(self.tmp_path)
        return {}

    def _load_file(self, path: Path) -> dict[str, Any]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise StateFormatError("State payload must be a JSON object.")
        return payload

    def _corrupt_archive_path(self) -> Path:
        return self._corrupt_archive_path_for(self.state_path)

    def _corrupt_archive_path_for(self, source_path: Path) -> Path:
        base_path = source_path.with_name(f"{source_path.name}.corrupt")
        if not base_path.exists():
            return base_path
        index = 1
        while True:
            archive_path = source_path.with_name(f"{source_path.name}.corrupt.{index}")
            if not archive_path.exists():
                return archive_path
            index += 1

    def _archive_corrupt_file(self, path: Path) -> None:
        if path.exists():
            path.replace(self._corrupt_archive_path_for(path))

    def save(self, state: dict[str, Any]) -> None:
        self.work_dir.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(state, ensure_ascii=False, indent=2)
        self.tmp_path.write_text(payload, encoding="utf-8")
        json.loads(self.tmp_path.read_text(encoding="utf-8"))
        if self.state_path.exists():
            try:
                self._load_file(self.state_path)
            except Exception:
                self.state_path.replace(self._corrupt_archive_path())
            else:
                self.state_path.replace(self.backup_path)
        self.tmp_path.replace(self.state_path)

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


HISTORY_FILENAME = "_pdf_split_history.json"


class HistoryFormatError(ValueError):
    pass


class OutputHistory:
    def __init__(self, work_dir: Path) -> None:
        self.work_dir = work_dir
        self.history_path = work_dir / HISTORY_FILENAME
        self.tmp_path = work_dir / f"{HISTORY_FILENAME}.tmp"

    def load(self) -> list[dict[str, Any]]:
        if not self.history_path.exists():
            return self._load_tmp_or_empty()
        try:
            return self._read_runs(self.history_path)
        except (json.JSONDecodeError, HistoryFormatError, AttributeError, OSError):
            if self.history_path.exists():
                self.history_path.replace(self._corrupt_archive_path())
            return self._load_tmp_or_empty()

    def _load_tmp_or_empty(self) -> list[dict[str, Any]]:
        if self.tmp_path.exists():
            try:
                runs = self._read_runs(self.tmp_path)
                self.tmp_path.replace(self.history_path)
                return runs
            except (json.JSONDecodeError, HistoryFormatError, AttributeError, OSError):
                self.tmp_path.replace(self._corrupt_archive_path_for(self.tmp_path))
        return []

    def _read_runs(self, path: Path) -> list[dict[str, Any]]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise HistoryFormatError("History payload must be a JSON object.")
        runs = payload.get("runs", [])
        if not isinstance(runs, list):
            raise HistoryFormatError("History runs must be a list.")
        return [run for run in runs if isinstance(run, dict)]

    def _corrupt_archive_path(self) -> Path:
        return self._corrupt_archive_path_for(self.history_path)

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

    def _load_for_append(self) -> list[dict[str, Any]]:
        return self.load()

    def append_run(self, summary: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
        record = {
            "version": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "summary": dict(summary),
            "items": [dict(item) for item in items],
        }
        payload = {"version": 1, "runs": [*self._load_for_append(), record]}
        self.work_dir.mkdir(parents=True, exist_ok=True)
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        self.tmp_path.write_text(text, encoding="utf-8")
        json.loads(self.tmp_path.read_text(encoding="utf-8"))
        self.tmp_path.replace(self.history_path)
        return record

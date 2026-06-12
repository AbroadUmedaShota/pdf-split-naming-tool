from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .state_schema import normalize_state_payload


STATE_FILENAME = "_pdf_split_state.json"
STATE_BAK_FILENAME = "_pdf_split_state.bak.json"
STATE_TMP_FILENAME = "_pdf_split_state.tmp"
STATE_TMP_PREFIX = "_pdf_split_state."
STATE_TMP_SUFFIX = ".tmp"


class StateFormatError(ValueError):
    pass


class StateManager:
    def __init__(self, work_dir: Path) -> None:
        self.work_dir = work_dir
        self.state_path = work_dir / STATE_FILENAME
        self.backup_path = work_dir / STATE_BAK_FILENAME
        # Fixed-name tmp path that pre-dates the pid-suffixed scheme.
        # Collected by _candidate_tmp_paths() so it participates in crash recovery.
        self.tmp_path = work_dir / STATE_TMP_FILENAME

    def _pid_tmp_path(self) -> Path:
        """Return a per-process tmp path to avoid write-write races on concurrent saves."""
        return self.work_dir / f"{STATE_TMP_PREFIX}{os.getpid()}{STATE_TMP_SUFFIX}"

    def _candidate_tmp_paths(self) -> list[Path]:
        """Collect all tmp files in work_dir (pid-suffixed and legacy fixed-name)."""
        try:
            return [
                p
                for p in self.work_dir.iterdir()
                if p.name.startswith(STATE_TMP_PREFIX) and p.name.endswith(STATE_TMP_SUFFIX)
            ]
        except OSError:
            return []

    def _best_valid_tmp(self) -> Path | None:
        """Return the most-recently-modified tmp file that passes JSON validation, or None."""
        candidates = self._candidate_tmp_paths()
        valid: list[tuple[float, Path]] = []
        for path in candidates:
            try:
                self._load_file(path, allow_invalid_input_paths=True)
                mtime = path.stat().st_mtime
                valid.append((mtime, path))
            except Exception:
                self._archive_corrupt_file(path)
        if not valid:
            return None
        valid.sort(key=lambda t: t[0], reverse=True)
        return valid[0][1]

    def load(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return self._load_without_state()
        try:
            return self._load_file(self.state_path, allow_invalid_input_paths=True)
        except Exception:
            self._archive_corrupt_file(self.state_path)
            return self._load_without_state()

    def _load_without_state(self) -> dict[str, Any]:
        """Recover when state_path is absent or corrupt.

        Priority: newest valid tmp > bak.  Both are compared by mtime when
        present so a crash between the bak-rotate and the tmp-rename does not
        silently revert to an older save.
        """
        tmp_path = self._best_valid_tmp()
        # 壊れた bak は候補に入れず、この時点で .corrupt へ退避する
        # （mtime 比較が「壊れているが新しい bak」を選ばないように）。
        bak_ok = False
        if self.backup_path.exists():
            try:
                self._load_file(self.backup_path, allow_invalid_input_paths=True)
                bak_ok = True
            except Exception:
                self._archive_corrupt_file(self.backup_path)

        # Decide which candidate is newer.
        use_tmp = False
        if tmp_path is not None:
            if bak_ok:
                try:
                    tmp_mtime = tmp_path.stat().st_mtime
                    bak_mtime = self.backup_path.stat().st_mtime
                    use_tmp = tmp_mtime >= bak_mtime
                except OSError:
                    use_tmp = True
            else:
                use_tmp = True

        if use_tmp and tmp_path is not None:
            payload = self._promote_tmp(tmp_path)
            if payload is not None:
                return payload

        if bak_ok:
            try:
                payload = self._load_file(self.backup_path, allow_invalid_input_paths=True)
            except Exception:
                self._archive_corrupt_file(self.backup_path)
            else:
                # 復元書き込みに失敗しても、読めた payload は返す（読み取りを優先）。
                try:
                    self._restore_loaded_payload(payload)
                except OSError:
                    pass
                return payload

        # Try remaining tmp candidates that were not yet processed.
        tmp_path2 = self._best_valid_tmp()
        if tmp_path2 is not None:
            payload = self._promote_tmp(tmp_path2)
            if payload is not None:
                return payload

        return {}

    def _promote_tmp(self, tmp_path: Path) -> dict[str, Any] | None:
        """Load *tmp_path* and try to promote it to state_path.

        Promotion failure (e.g. locked file) is non-fatal: the loaded payload is
        still returned so a recoverable save is never discarded.
        """
        try:
            payload = self._load_file(tmp_path, allow_invalid_input_paths=True)
        except Exception:
            self._archive_corrupt_file(tmp_path)
            return None
        try:
            tmp_path.replace(self.state_path)
        except OSError:
            pass
        return payload

    def _restore_loaded_payload(self, payload: dict[str, Any]) -> None:
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_file(self, path: Path, *, allow_invalid_input_paths: bool = False) -> dict[str, Any]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        try:
            return normalize_state_payload(payload, allow_invalid_input_paths=allow_invalid_input_paths)
        except TypeError as exc:
            raise StateFormatError(str(exc)) from exc

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

    def _cleanup_stale_tmps(self) -> None:
        """Remove tmp files left by crashed processes after a successful commit.

        Only files whose mtime is older than the just-committed state are removed,
        so a concurrent save in progress (mtime >= state) is never touched.
        Errors are silently swallowed; cleanup is best-effort.
        """
        try:
            committed_mtime = self.state_path.stat().st_mtime
        except OSError:
            return
        own_pid_name = self._pid_tmp_path().name
        for candidate in self._candidate_tmp_paths():
            if candidate.name == own_pid_name:
                continue
            try:
                if candidate.stat().st_mtime < committed_mtime:
                    candidate.unlink()
            except OSError:
                pass

    def _archive_corrupt_file(self, path: Path) -> None:
        if path.exists():
            path.replace(self._corrupt_archive_path_for(path))

    def save(self, state: dict[str, Any]) -> None:
        self.work_dir.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(state, ensure_ascii=False, indent=2)
        pid_tmp = self._pid_tmp_path()
        pid_tmp.write_text(payload, encoding="utf-8")
        # Verify the written content is valid JSON before committing.
        json.loads(pid_tmp.read_text(encoding="utf-8"))
        if self.state_path.exists():
            try:
                self._load_file(self.state_path)
            except Exception:
                self.state_path.replace(self._corrupt_archive_path_for(self.state_path))
            else:
                self.state_path.replace(self.backup_path)
        pid_tmp.replace(self.state_path)
        self._cleanup_stale_tmps()

from __future__ import annotations

import json
from pathlib import Path

from pdf_splitter_tool.state import STATE_BAK_FILENAME, STATE_FILENAME, STATE_TMP_FILENAME, StateManager


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_load_keeps_readable_backup_when_restore_write_fails(monkeypatch, tmp_path: Path) -> None:
    manager = StateManager(tmp_path)
    backup_state = {"schema_version": 1, "input_paths": ["backup.pdf"], "current_page": 7}
    write_json(manager.backup_path, backup_state)
    original_write_text = Path.write_text

    def fail_state_restore(path: Path, *args, **kwargs):
        if path == manager.state_path:
            raise OSError("simulated restore write failure")
        return original_write_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_state_restore)

    assert manager.load() == backup_state
    assert manager.backup_path.exists()
    assert json.loads(manager.backup_path.read_text(encoding="utf-8")) == backup_state
    assert not (tmp_path / f"{STATE_BAK_FILENAME}.corrupt").exists()
    assert not manager.state_path.exists()


def test_load_keeps_tmp_when_promotion_replace_fails(monkeypatch, tmp_path: Path) -> None:
    manager = StateManager(tmp_path)
    tmp_state = {"schema_version": 1, "input_paths": ["tmp.pdf"], "current_page": 8}
    write_json(manager.tmp_path, tmp_state)
    original_replace = Path.replace

    def fail_tmp_promotion(path: Path, target: Path):
        if path == manager.tmp_path and target == manager.state_path:
            raise OSError("simulated tmp promotion failure")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_tmp_promotion)

    assert manager.load() == tmp_state
    assert manager.tmp_path.exists()
    assert json.loads(manager.tmp_path.read_text(encoding="utf-8")) == tmp_state
    assert not (tmp_path / f"{STATE_TMP_FILENAME}.corrupt").exists()
    assert not manager.state_path.exists()


def test_load_keeps_tmp_when_promotion_replace_fails_after_primary_and_backup_are_unusable(
    monkeypatch, tmp_path: Path
) -> None:
    manager = StateManager(tmp_path)
    manager.state_path.write_text("{broken primary", encoding="utf-8")
    manager.backup_path.write_text("{broken backup", encoding="utf-8")
    tmp_state = {"schema_version": 1, "input_paths": ["tmp-after-corrupt.pdf"], "current_page": 9}
    write_json(manager.tmp_path, tmp_state)
    original_replace = Path.replace

    def fail_tmp_promotion(path: Path, target: Path):
        if path == manager.tmp_path and target == manager.state_path:
            raise OSError("simulated tmp promotion failure")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_tmp_promotion)

    assert manager.load() == tmp_state
    assert manager.tmp_path.exists()
    assert json.loads(manager.tmp_path.read_text(encoding="utf-8")) == tmp_state
    assert (tmp_path / f"{STATE_FILENAME}.corrupt").exists()
    assert (tmp_path / f"{STATE_BAK_FILENAME}.corrupt").exists()
    assert not (tmp_path / f"{STATE_TMP_FILENAME}.corrupt").exists()

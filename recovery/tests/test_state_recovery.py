from __future__ import annotations

import json
from pathlib import Path

from pdf_splitter_tool.sidecar import handle_request
from pdf_splitter_tool.state import STATE_BAK_FILENAME, STATE_FILENAME, STATE_TMP_FILENAME, StateManager


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def write_corrupt_json(path: Path) -> None:
    path.write_text("{not valid json", encoding="utf-8")


def test_state_load_restores_backup_when_primary_is_corrupt(tmp_path: Path) -> None:
    primary_path = tmp_path / STATE_FILENAME
    backup_path = tmp_path / STATE_BAK_FILENAME
    backup_state = {"schema_version": 1, "input_paths": ["source.pdf"], "current_page": 2}
    write_corrupt_json(primary_path)
    write_json(backup_path, backup_state)

    response = handle_request({"command": "state_load", "work_dir": str(tmp_path)})

    assert response["ok"] is True
    assert response["command"] == "state_load"
    assert response["state"] == backup_state
    assert primary_path.exists()
    assert (tmp_path / f"{STATE_FILENAME}.corrupt").read_text(encoding="utf-8") == "{not valid json"
    assert json.loads(primary_path.read_text(encoding="utf-8")) == backup_state


def test_state_load_promotes_tmp_when_state_and_backup_are_missing(tmp_path: Path) -> None:
    primary_path = tmp_path / STATE_FILENAME
    backup_path = tmp_path / STATE_BAK_FILENAME
    tmp_path_state = tmp_path / STATE_TMP_FILENAME
    tmp_state = {"schema_version": 1, "input_paths": ["tmp-source.pdf"], "current_page": 3}
    write_json(tmp_path_state, tmp_state)

    response = handle_request({"command": "state_load", "work_dir": str(tmp_path)})

    assert response["ok"] is True
    assert response["state"] == tmp_state
    assert primary_path.exists()
    assert not backup_path.exists()
    assert not tmp_path_state.exists()
    assert json.loads(primary_path.read_text(encoding="utf-8")) == tmp_state


def test_state_load_returns_empty_state_when_all_state_files_are_corrupt(tmp_path: Path) -> None:
    primary_path = tmp_path / STATE_FILENAME
    backup_path = tmp_path / STATE_BAK_FILENAME
    tmp_path_state = tmp_path / STATE_TMP_FILENAME
    for path in (primary_path, backup_path, tmp_path_state):
        write_corrupt_json(path)

    response = handle_request({"command": "state_load", "work_dir": str(tmp_path)})

    assert response["ok"] is True
    assert response["state"] == {}
    assert not primary_path.exists()
    assert not backup_path.exists()
    assert not tmp_path_state.exists()
    assert (tmp_path / f"{STATE_FILENAME}.corrupt").exists()
    assert (tmp_path / f"{STATE_BAK_FILENAME}.corrupt").exists()
    assert (tmp_path / f"{STATE_TMP_FILENAME}.corrupt").exists()


def test_state_load_accepts_legacy_payload_without_schema_version(tmp_path: Path) -> None:
    primary_path = tmp_path / STATE_FILENAME
    legacy_state = {"input_paths": ["legacy.pdf"], "current_page": 4}
    write_json(primary_path, legacy_state)

    response = handle_request({"command": "state_load", "work_dir": str(tmp_path)})

    assert response["ok"] is True
    assert response["state"] == legacy_state


def test_state_save_archives_readable_primary_as_backup(tmp_path: Path) -> None:
    manager = StateManager(tmp_path)
    original_state = {"schema_version": 1, "input_paths": ["before.pdf"], "current_page": 2}
    next_state = {"schema_version": 1, "input_paths": ["after.pdf"], "current_page": 3}
    write_json(manager.state_path, original_state)

    manager.save(next_state)

    assert json.loads(manager.state_path.read_text(encoding="utf-8")) == next_state
    assert json.loads(manager.backup_path.read_text(encoding="utf-8")) == original_state
    assert not manager.tmp_path.exists()
    assert not (tmp_path / f"{STATE_FILENAME}.corrupt").exists()


def test_state_save_archives_corrupt_primary_as_corrupt(tmp_path: Path) -> None:
    manager = StateManager(tmp_path)
    next_state = {"schema_version": 1, "input_paths": ["after-corrupt.pdf"], "current_page": 4}
    write_corrupt_json(manager.state_path)

    manager.save(next_state)

    assert json.loads(manager.state_path.read_text(encoding="utf-8")) == next_state
    assert (tmp_path / f"{STATE_FILENAME}.corrupt").read_text(encoding="utf-8") == "{not valid json"
    assert not manager.backup_path.exists()
    assert not manager.tmp_path.exists()


def test_state_save_validates_tmp_json_before_replacing_primary(monkeypatch, tmp_path: Path) -> None:
    manager = StateManager(tmp_path)
    original_state = {"schema_version": 1, "input_paths": ["before-validation.pdf"], "current_page": 5}
    next_state = {"schema_version": 1, "input_paths": ["after-validation.pdf"], "current_page": 6}
    write_json(manager.state_path, original_state)
    original_read_text = Path.read_text

    def corrupt_tmp_read(path: Path, *args, **kwargs):
        # save() は pid 付き tmp（write-write レース対策）へ書き込む。
        if path == manager._pid_tmp_path():
            return "{invalid tmp json"
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", corrupt_tmp_read)

    try:
        manager.save(next_state)
    except json.JSONDecodeError:
        pass
    else:
        raise AssertionError("StateManager.save did not validate tmp JSON before publishing")

    assert json.loads(original_read_text(manager.state_path, encoding="utf-8")) == original_state
    assert original_read_text(manager._pid_tmp_path(), encoding="utf-8")
    assert not manager.backup_path.exists()

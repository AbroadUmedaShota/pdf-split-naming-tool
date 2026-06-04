from __future__ import annotations

from pathlib import Path

from pdf_splitter_tool.runtime import default_work_dir
from pdf_splitter_tool.state import StateManager


def test_default_work_dir_uses_explicit_override(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PDF_ORGANIZER_WORK_DIR", str(tmp_path / "work"))

    assert default_work_dir() == tmp_path / "work"


def test_default_work_dir_uses_appdata_on_windows_style_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("PDF_ORGANIZER_WORK_DIR", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))

    assert default_work_dir() == tmp_path / "AppData" / "Roaming" / "PDF整理ツール"


def test_state_manager_writes_state_and_backup(tmp_path: Path) -> None:
    manager = StateManager(tmp_path)

    manager.save({"version": 1, "value": "first"})
    manager.save({"version": 1, "value": "second"})

    assert manager.load()["value"] == "second"
    assert manager.backup_path.exists()


def test_state_manager_falls_back_to_backup_when_state_is_broken(tmp_path: Path) -> None:
    manager = StateManager(tmp_path)

    manager.save({"version": 2, "value": "backup"})
    manager.save({"version": 2, "value": "current"})
    manager.state_path.write_text("{broken", encoding="utf-8")

    assert manager.load()["value"] == "backup"
    assert manager.state_path.exists()
    assert manager.backup_path.exists()

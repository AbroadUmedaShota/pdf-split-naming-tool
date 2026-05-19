from __future__ import annotations

import sys
from pathlib import Path

from pdf_splitter_tool.app import default_work_dir


def test_default_work_dir_uses_current_directory_when_not_frozen(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delattr(sys, "frozen", raising=False)

    assert default_work_dir() == tmp_path


def test_default_work_dir_uses_executable_parent_when_frozen(monkeypatch, tmp_path: Path) -> None:
    exe_path = tmp_path / "dist" / "pdf-split-naming-tool-recovery.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_path))

    assert default_work_dir() == exe_path.parent

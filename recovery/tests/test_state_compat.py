from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from pdf_splitter_tool.sidecar import handle_request
from pdf_splitter_tool.state import STATE_FILENAME, StateManager


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "state"


def load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def copy_fixture_to_work_dir(name: str, work_dir: Path) -> Path:
    state_path = work_dir / STATE_FILENAME
    shutil.copyfile(FIXTURE_DIR / name, state_path)
    return state_path


def test_state_manager_loads_legacy_state_without_schema_version(tmp_path: Path) -> None:
    expected = load_fixture("legacy_no_schema.json")
    copy_fixture_to_work_dir("legacy_no_schema.json", tmp_path)

    loaded = StateManager(tmp_path).load()

    assert loaded == expected
    assert "schema_version" not in loaded


def test_state_manager_preserves_unknown_keys(tmp_path: Path) -> None:
    expected = load_fixture("unknown_keys.json")
    copy_fixture_to_work_dir("unknown_keys.json", tmp_path)

    loaded = StateManager(tmp_path).load()

    assert loaded == expected
    assert loaded["future_client_state"] == expected["future_client_state"]


def test_state_load_reports_missing_pdf_without_removing_payload(tmp_path: Path) -> None:
    expected = load_fixture("missing_pdf_path.json")
    missing_pdf = tmp_path / "missing-fixture-input.pdf"
    expected["input_paths"] = [str(missing_pdf)]
    (tmp_path / STATE_FILENAME).write_text(json.dumps(expected, ensure_ascii=False), encoding="utf-8")

    response = handle_request({"command": "state_load", "work_dir": str(tmp_path)})

    assert response["ok"] is True
    assert response["state"] == expected
    assert response["state"]["input_paths"] == expected["input_paths"]
    assert response["messages"] == ["missing_input_pdf"]
    assert response["missing_input_paths"] == expected["input_paths"]

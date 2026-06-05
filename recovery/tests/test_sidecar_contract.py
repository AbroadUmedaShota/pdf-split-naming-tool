from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import fitz

from pdf_splitter_tool.sidecar import handle_request


def make_pdf(path: Path, pages: int = 2) -> None:
    doc = fitz.open()
    try:
        for index in range(pages):
            page = doc.new_page()
            page.insert_text((72, 72), f"Contract page {index + 1}")
        doc.save(path)
    finally:
        doc.close()


def assert_json_ready(response: dict[str, Any]) -> dict[str, Any]:
    encoded = json.dumps(response, ensure_ascii=False)
    decoded = json.loads(encoded)
    assert isinstance(decoded, dict)
    return decoded


def assert_required_keys(response: dict[str, Any], keys: set[str]) -> None:
    assert keys <= response.keys()


def segment_request(pdf_path: Path) -> dict[str, Any]:
    return {
        "pdf_path": str(pdf_path),
        "start_page": 1,
        "end_page": 2,
        "metadata": {"box_no": "1", "binder_no": "2", "seq": "3"},
    }


def test_pdf_info_response_public_contract_is_json_ready(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_pdf(source, pages=2)

    response = assert_json_ready(handle_request({"command": "pdf_info", "pdf_path": str(source)}))

    assert_required_keys(response, {"ok", "command", "pdf_path", "page_count", "page_numbers", "naming_template"})
    assert response["ok"] is True
    assert response["command"] == "pdf_info"
    assert response["pdf_path"] == str(source)
    assert response["page_count"] == 2
    assert response["page_numbers"] == [1, 2]
    assert isinstance(response["naming_template"], str)


def test_page_preview_response_public_contract_is_json_ready(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_pdf(source, pages=1)

    response = assert_json_ready(handle_request({"command": "page_preview", "pdf_path": str(source), "page_no": 1}))

    assert_required_keys(response, {"ok", "command", "pdf_path", "page_no", "page_count", "image_data_url"})
    assert response["ok"] is True
    assert response["command"] == "page_preview"
    assert response["pdf_path"] == str(source)
    assert response["page_no"] == 1
    assert response["page_count"] == 1
    assert isinstance(response["image_data_url"], str)
    assert response["image_data_url"].startswith("data:image/png;base64,")


def test_page_preview_rejects_zero_page_number_with_json_ready_error(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_pdf(source, pages=2)

    response = assert_json_ready(handle_request({"command": "page_preview", "pdf_path": str(source), "page_no": 0}))

    assert_required_keys(response, {"ok", "command", "error", "error_type"})
    assert response["ok"] is False
    assert response["command"] == "page_preview"
    assert response["error_type"] == "ValueError"
    assert "page_no must be between 1" in response["error"]


def test_page_preview_rejects_page_after_page_count_with_json_ready_error(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_pdf(source, pages=2)

    response = assert_json_ready(handle_request({"command": "page_preview", "pdf_path": str(source), "page_no": 3}))

    assert_required_keys(response, {"ok", "command", "error", "error_type"})
    assert response["ok"] is False
    assert response["command"] == "page_preview"
    assert response["error_type"] == "ValueError"
    assert "page_no must be between 1" in response["error"]


def test_preflight_response_public_contract_is_json_ready(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    output_dir = tmp_path / "output"
    make_pdf(source, pages=2)

    response = assert_json_ready(
        handle_request({"command": "preflight", "output_dir": str(output_dir), "segments": [segment_request(source)]})
    )

    assert_required_keys(response, {"ok", "command", "can_run", "output_dir", "messages", "checks"})
    assert response["ok"] is True
    assert response["command"] == "preflight"
    assert response["can_run"] is True
    assert response["output_dir"] == str(output_dir)
    assert isinstance(response["messages"], list)
    assert isinstance(response["checks"], list)
    assert len(response["checks"]) == 1

    check = response["checks"][0]
    assert_required_keys(
        check,
        {
            "ok",
            "filename",
            "output_path",
            "messages",
            "requested_filename",
            "requested_path",
            "existing_path",
            "has_existing_output",
            "metadata",
            "pages",
            "pdf_path",
        },
    )
    assert check["ok"] is True
    assert check["filename"] == "01_02_003.pdf"
    assert check["pages"] == "1-2"
    assert check["pdf_path"] == str(source)
    assert isinstance(check["messages"], list)
    assert isinstance(check["metadata"], dict)
    assert check["has_existing_output"] is False


def test_export_response_public_contract_is_json_ready(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    output_dir = tmp_path / "output"
    make_pdf(source, pages=2)

    response = assert_json_ready(
        handle_request({"command": "export", "output_dir": str(output_dir), "segments": [segment_request(source)]})
    )

    assert_required_keys(response, {"ok", "command", "output_dir", "summary", "items"})
    assert response["ok"] is True
    assert response["command"] == "export"
    assert response["output_dir"] == str(output_dir)
    assert isinstance(response["summary"], dict)
    assert response["summary"]["created"] == 1
    assert response["summary"]["failed"] == 0
    assert isinstance(response["items"], list)
    assert len(response["items"]) == 1

    item = response["items"][0]
    assert_required_keys(item, {"ok", "filename", "output_path", "messages", "status", "sha256", "pages", "pdf_path"})
    assert item["status"] == "created"
    assert item["filename"] == "01_02_003.pdf"
    assert item["output_path"] == str(output_dir / "01_02_003.pdf")
    assert isinstance(item["sha256"], str)
    assert len(item["sha256"]) == 64
    assert Path(item["output_path"]).exists()


def test_state_save_response_public_contract_is_json_ready(tmp_path: Path) -> None:
    state = {"version": 1, "input_paths": ["source.pdf"], "current_page": 1}

    response = assert_json_ready(handle_request({"command": "state_save", "work_dir": str(tmp_path), "state": state}))

    assert_required_keys(response, {"ok", "command", "work_dir"})
    assert response["ok"] is True
    assert response["command"] == "state_save"
    assert response["work_dir"] == str(tmp_path)


def test_state_load_response_public_contract_is_json_ready(tmp_path: Path) -> None:
    state = {"version": 1, "input_paths": ["source.pdf"], "current_page": 1}
    save_response = handle_request({"command": "state_save", "work_dir": str(tmp_path), "state": state})
    assert save_response["ok"] is True

    response = assert_json_ready(handle_request({"command": "state_load", "work_dir": str(tmp_path)}))

    assert_required_keys(response, {"ok", "command", "work_dir", "state"})
    assert response["ok"] is True
    assert response["command"] == "state_load"
    assert response["work_dir"] == str(tmp_path)
    assert isinstance(response["state"], dict)
    assert response["state"]["version"] == 1
    assert response["state"]["current_page"] == 1


def test_unsupported_command_error_contract_is_json_ready() -> None:
    response = assert_json_ready(handle_request({"command": "unknown_command"}))

    assert_required_keys(response, {"ok", "command", "error"})
    assert response["ok"] is False
    assert response["command"] == "unknown_command"
    assert isinstance(response["error"], str)
    assert "Unsupported sidecar command" in response["error"]


def test_non_object_request_error_contract_is_json_ready() -> None:
    response = assert_json_ready(handle_request(["not", "an", "object"]))  # type: ignore[arg-type]

    assert_required_keys(response, {"ok", "command", "error", "error_type"})
    assert response["ok"] is False
    assert response["command"] == ""
    assert response["error_type"] == "TypeError"
    assert isinstance(response["error"], str)
    assert "JSON object" in response["error"]

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import fitz

from pdf_splitter_tool.sidecar import handle_request


def make_pdf(path: Path, pages: int) -> None:
    doc = fitz.open()
    for index in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"Page {index + 1}")
    doc.save(path)
    doc.close()


def test_sidecar_pdf_info_returns_import_metadata(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_pdf(source, 3)

    response = handle_request({"command": "pdf_info", "pdf_path": str(source)})

    assert response["ok"] is True
    assert response["command"] == "pdf_info"
    assert response["pdf_path"] == str(source)
    assert response["page_count"] == 3
    assert "page_numbers" not in response
    assert response["naming_template"] == "{box_no:0>2}_{binder_no:0>2}_{seq:0>3}.pdf"


def test_sidecar_page_preview_returns_jpeg_data_url(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_pdf(source, 1)

    response = handle_request({"command": "page_preview", "pdf_path": str(source), "page_no": 1})

    assert response["ok"] is True
    assert response["command"] == "page_preview"
    assert response["image_data_url"].startswith("data:image/jpeg;base64,")
    assert response["page_count"] == 1


def test_sidecar_preflight_returns_json_ready_checks(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_pdf(source, 2)

    response = handle_request(
        {
            "command": "preflight",
            "output_dir": str(tmp_path / "output"),
            "segments": [
                {
                    "pdf_path": str(source),
                    "start_page": 1,
                    "end_page": 2,
                    "metadata": {"box_no": "1", "binder_no": "2", "seq": "3"},
                }
            ],
        }
    )

    assert response["ok"] is True
    assert response["command"] == "preflight"
    assert response["can_run"] is True
    assert response["checks"][0]["filename"] == "01_02_003.pdf"
    assert response["checks"][0]["pages"] == "1-2"


def test_sidecar_preflight_blocks_empty_segments(tmp_path: Path) -> None:
    response = handle_request({"command": "preflight", "output_dir": str(tmp_path / "output"), "segments": []})

    assert response["ok"] is False
    assert response["can_run"] is False
    assert response["checks"] == []
    assert "no_segments" in response["messages"]


def test_sidecar_preflight_blocks_missing_output_dir(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_pdf(source, 1)

    response = handle_request(
        {
            "command": "preflight",
            "output_dir": "",
            "segments": [
                {
                    "pdf_path": str(source),
                    "start_page": 1,
                    "end_page": 1,
                    "metadata": {"box_no": "1", "binder_no": "2", "seq": "3"},
                }
            ],
        }
    )

    assert response["ok"] is False
    assert response["can_run"] is False
    assert response["checks"] == []
    assert "missing_output_dir" in response["messages"]


def test_sidecar_state_load_and_save_round_trip(tmp_path: Path) -> None:
    state = {"version": 1, "input_paths": ["source.pdf"], "current_page": 2}

    save_response = handle_request({"command": "state_save", "work_dir": str(tmp_path), "state": state})
    load_response = handle_request({"command": "state_load", "work_dir": str(tmp_path)})

    assert save_response["ok"] is True
    assert load_response["ok"] is True
    assert load_response["state"] == state


def test_sidecar_export_writes_pdf_and_sha256(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    output_dir = tmp_path / "output"
    make_pdf(source, 2)

    response = handle_request(
        {
            "command": "export",
            "output_dir": str(output_dir),
            "segments": [
                {
                    "pdf_path": str(source),
                    "start_page": 2,
                    "end_page": 2,
                    "metadata": {"box_no": "1", "binder_no": "2", "seq": "3"},
                }
            ],
        }
    )

    assert response["ok"] is True
    assert response["summary"] == {"created": 1, "failed": 0}
    assert response["items"][0]["status"] == "created"
    assert response["items"][0]["sha256"]
    output_path = Path(response["items"][0]["output_path"])
    assert output_path == output_dir / "01_02_003.pdf"
    with fitz.open(output_path) as doc:
        assert doc.page_count == 1
        assert "Page 2" in doc.load_page(0).get_text()


def test_sidecar_export_blocks_invalid_segments(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    output_dir = tmp_path / "output"
    make_pdf(source, 1)

    response = handle_request(
        {
            "command": "export",
            "output_dir": str(output_dir),
            "segments": [
                {
                    "pdf_path": str(source),
                    "start_page": 1,
                    "end_page": 1,
                    "metadata": {"box_no": "1", "binder_no": "2"},
                }
            ],
        }
    )

    assert response["ok"] is False
    assert response["summary"] == {"created": 0, "failed": 1}
    assert response["items"][0]["status"] == "failed"
    assert any("連番" in message for message in response["items"][0]["messages"])
    assert not output_dir.exists()


def test_sidecar_returns_json_error_for_non_object_request() -> None:
    response = handle_request(["not", "an", "object"])  # type: ignore[arg-type]

    assert response["ok"] is False
    assert response["command"] == ""
    assert response["error_type"] == "TypeError"
    assert "JSON object" in response["error"]


def test_sidecar_cli_reads_request_file_and_prints_json(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    request_path = tmp_path / "request.json"
    make_pdf(source, 1)
    request_path.write_text(
        json.dumps(
            {
                "command": "preflight",
                "output_dir": str(tmp_path / "output"),
                "segments": [
                    {
                        "pdf_path": str(source),
                        "start_page": 1,
                        "end_page": 1,
                        "metadata": {"box_no": "1", "binder_no": "2", "seq": "3"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [sys.executable, "-m", "pdf_splitter_tool", "--sidecar-request", str(request_path)],
        check=True,
        capture_output=True,
        text=True,
    )

    response = json.loads(completed.stdout)
    assert response["ok"] is True
    assert response["checks"][0]["filename"] == "01_02_003.pdf"
    # ISS-013: sidecar CLI response must be compact JSON (no indent).
    assert "\n" not in completed.stdout.rstrip("\n")

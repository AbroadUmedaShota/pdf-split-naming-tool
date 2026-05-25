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


def make_text_pdf(path: Path, text: str) -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    doc.save(path)
    doc.close()


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
                    "page_numbers": [2, 1],
                    "rotations": {"2": 90},
                }
            ],
        }
    )

    assert response["ok"] is True
    assert response["command"] == "preflight"
    assert response["can_run"] is True
    assert response["checks"][0]["filename"] == "01_02_003.pdf"
    assert response["checks"][0]["page_plan"]["page_numbers"] == [2, 1]
    assert response["checks"][0]["page_plan"]["rotations"] == {"2": 90}


def test_sidecar_preflight_blocks_empty_segments(tmp_path: Path) -> None:
    response = handle_request(
        {
            "command": "preflight",
            "output_dir": str(tmp_path / "output"),
            "segments": [],
        }
    )

    assert response["ok"] is False
    assert response["can_run"] is False
    assert response["checks"] == []
    assert "no_segments" in response["messages"]


def test_sidecar_pdf_info_returns_import_metadata(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_pdf(source, 3)

    response = handle_request({"command": "pdf_info", "pdf_path": str(source)})

    assert response["ok"] is True
    assert response["command"] == "pdf_info"
    assert response["pdf_path"] == str(source)
    assert response["page_count"] == 3
    assert response["page_numbers"] == [1, 2, 3]
    assert response["has_text_layer"] is True
    assert response["default_preset"]["id"] == "yoshida-elsis"
    assert response["default_preset"]["naming_template"] == "{box_no:0>2}_{binder_no:0>2}_{seq:0>3}.pdf"


def test_sidecar_returns_json_error_when_pdf_cannot_be_opened(tmp_path: Path) -> None:
    missing_pdf = tmp_path / "missing.pdf"

    response = handle_request({"command": "pdf_info", "pdf_path": str(missing_pdf)})

    assert response["ok"] is False
    assert response["command"] == "pdf_info"
    assert response["error_type"]
    assert str(missing_pdf) in response["error"]


def test_sidecar_returns_json_error_for_non_object_request() -> None:
    response = handle_request(["not", "an", "object"])  # type: ignore[arg-type]

    assert response["ok"] is False
    assert response["command"] == ""
    assert response["error_type"] == "TypeError"
    assert "JSON object" in response["error"]


def test_sidecar_page_text_returns_text_and_metadata_suggestions(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_text_pdf(source, "Box Number 01\nCompany Name Acme Inc\nDocument Name Lease Agreement")

    response = handle_request({"command": "page_text", "pdf_path": str(source), "page_no": 1, "suggestion_limit": 3})

    assert response["ok"] is True
    assert response["command"] == "page_text"
    assert response["pdf_path"] == str(source)
    assert response["page_no"] == 1
    assert "Company Name Acme Inc" in response["text"]
    assert response["suggestions"] == ["01", "Acme Inc", "Lease Agreement"]


def test_sidecar_presets_loads_local_presets_for_ui_selection(tmp_path: Path) -> None:
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    (work_dir / "presets.json").write_text(
        json.dumps(
            {
                "active_preset_id": "case",
                "presets": [
                    {
                        "id": "case",
                        "name": "Case",
                        "fields": [{"key": "seq", "label": "Seq", "required": True}],
                        "naming_template": "{seq}.pdf",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    response = handle_request({"command": "presets", "work_dir": str(work_dir)})

    assert response["ok"] is True
    assert response["command"] == "presets"
    assert response["active_preset_id"] == "case"
    assert response["presets"][0]["id"] == "case"
    assert response["presets"][0]["fields"][0]["key"] == "seq"
    assert any(preset["id"] == "yoshida-elsis" for preset in response["presets"])


def test_sidecar_history_loads_local_output_runs_for_history_view(tmp_path: Path) -> None:
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    (work_dir / "_pdf_split_history.json").write_text(
        json.dumps(
            {
                "version": 1,
                "runs": [
                    {
                        "version": 1,
                        "created_at": "2026-05-25T00:00:00+00:00",
                        "summary": {"created": 1, "failed": 0},
                        "items": [{"source_pdf": "source.pdf", "status": "created", "output_path": "output/01.pdf"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    response = handle_request({"command": "history", "work_dir": str(work_dir)})

    assert response["ok"] is True
    assert response["command"] == "history"
    assert response["work_dir"] == str(work_dir)
    assert response["count"] == 1
    assert response["runs"][0]["summary"]["created"] == 1
    assert response["runs"][0]["items"][0]["output_path"] == "output/01.pdf"


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
                    "start_page": 1,
                    "end_page": 2,
                    "metadata": {"box_no": "1", "binder_no": "2", "seq": "3"},
                    "page_numbers": [2],
                }
            ],
        }
    )

    assert response["ok"] is True
    assert response["summary"] == {"created": 1, "reused": 0, "skipped": 0, "failed": 0}
    assert response["items"][0]["status"] == "created"
    assert response["items"][0]["sha256"]
    output_path = Path(response["items"][0]["output_path"])
    assert output_path == output_dir / "01_02_003.pdf"
    with fitz.open(output_path) as doc:
        assert doc.page_count == 1
        assert "Page 2" in doc.load_page(0).get_text()


def test_sidecar_export_blocks_empty_segments_without_history(tmp_path: Path) -> None:
    work_dir = tmp_path / "work"

    response = handle_request(
        {
            "command": "export",
            "work_dir": str(work_dir),
            "output_dir": str(tmp_path / "output"),
            "segments": [],
        }
    )

    history_response = handle_request({"command": "history", "work_dir": str(work_dir)})

    assert response["ok"] is False
    assert response["summary"] == {"created": 0, "reused": 0, "skipped": 0, "failed": 0}
    assert response["items"] == []
    assert response["history"] is None
    assert response["history_error"] is None
    assert "no_segments" in response["messages"]
    assert history_response["count"] == 0


def test_sidecar_export_appends_local_history_run(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    make_pdf(source, 1)

    response = handle_request(
        {
            "command": "export",
            "work_dir": str(work_dir),
            "output_dir": str(output_dir),
            "segments": [
                {
                    "pdf_path": str(source),
                    "start_page": 1,
                    "end_page": 1,
                    "metadata": {"box_no": "4", "binder_no": "5", "seq": "6"},
                }
            ],
        }
    )

    history_response = handle_request({"command": "history", "work_dir": str(work_dir)})

    assert response["ok"] is True
    assert history_response["count"] == 1
    run = history_response["runs"][0]
    assert run["summary"]["created"] == 1
    assert run["summary"]["success"] == 1
    assert run["summary"]["output_dir"] == str(output_dir)
    assert run["items"][0]["status"] == "created"
    assert run["items"][0]["requested_filename"] == "04_05_006.pdf"
    assert run["items"][0]["output_path"] == str(output_dir / "04_05_006.pdf")
    assert run["items"][0]["sha256"]


def test_sidecar_export_blocks_all_outputs_when_preflight_has_invalid_segment(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    make_pdf(source, 1)

    response = handle_request(
        {
            "command": "export",
            "work_dir": str(work_dir),
            "output_dir": str(output_dir),
            "segments": [
                {
                    "pdf_path": str(source),
                    "start_page": 1,
                    "end_page": 1,
                    "metadata": {"box_no": "1", "binder_no": "2", "seq": "1"},
                },
                {
                    "pdf_path": str(source),
                    "start_page": 1,
                    "end_page": 1,
                    "metadata": {"box_no": "1", "binder_no": "2"},
                },
            ],
        }
    )

    history_response = handle_request({"command": "history", "work_dir": str(work_dir)})

    assert response["ok"] is False
    assert response["summary"] == {"created": 0, "reused": 0, "skipped": 0, "failed": 2}
    assert response["items"][0]["status"] == "failed"
    assert response["items"][0]["messages"] == ["preflight_blocked"]
    assert response["items"][1]["status"] == "failed"
    assert any("seq" in message or "連番" in message for message in response["items"][1]["messages"])
    assert not (output_dir / "01_02_001.pdf").exists()
    assert history_response["count"] == 0


def test_sidecar_export_keeps_successful_items_when_later_item_fails(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    missing_source = tmp_path / "missing.pdf"
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    make_pdf(source, 1)

    response = handle_request(
        {
            "command": "export",
            "work_dir": str(work_dir),
            "output_dir": str(output_dir),
            "segments": [
                {
                    "pdf_path": str(source),
                    "start_page": 1,
                    "end_page": 1,
                    "metadata": {"box_no": "1", "binder_no": "2", "seq": "1"},
                },
                {
                    "pdf_path": str(missing_source),
                    "start_page": 1,
                    "end_page": 1,
                    "metadata": {"box_no": "1", "binder_no": "2", "seq": "2"},
                },
            ],
        }
    )

    history_response = handle_request({"command": "history", "work_dir": str(work_dir)})

    assert response["ok"] is False
    assert response["summary"] == {"created": 1, "reused": 0, "skipped": 0, "failed": 1}
    assert response["items"][0]["status"] == "created"
    assert Path(response["items"][0]["output_path"]).exists()
    assert response["items"][1]["status"] == "failed"
    assert "missing.pdf" in response["items"][1]["error"]
    assert history_response["count"] == 1
    assert history_response["runs"][0]["summary"]["failed"] == 1


def test_sidecar_export_returns_items_when_history_save_fails(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    output_dir = tmp_path / "output"
    blocked_work_dir = tmp_path / "history-blocker"
    blocked_work_dir.write_text("not a directory", encoding="utf-8")
    make_pdf(source, 1)

    response = handle_request(
        {
            "command": "export",
            "work_dir": str(blocked_work_dir),
            "output_dir": str(output_dir),
            "segments": [
                {
                    "pdf_path": str(source),
                    "start_page": 1,
                    "end_page": 1,
                    "metadata": {"box_no": "7", "binder_no": "8", "seq": "9"},
                }
            ],
        }
    )

    assert response["ok"] is False
    assert response["summary"] == {"created": 1, "reused": 0, "skipped": 0, "failed": 0}
    assert response["items"][0]["status"] == "created"
    assert Path(response["items"][0]["output_path"]).exists()
    assert response["history"] is None
    assert response["history_error"]["error_type"]
    assert "history-blocker" in response["history_error"]["error"]


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


def test_sidecar_cli_prints_json_error_for_invalid_json(tmp_path: Path) -> None:
    request_path = tmp_path / "request.json"
    request_path.write_text("{not json", encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, "-m", "pdf_splitter_tool", "--sidecar-request", str(request_path)],
        check=True,
        capture_output=True,
        text=True,
    )

    response = json.loads(completed.stdout)
    assert response["ok"] is False
    assert response["command"] == ""
    assert response["error_type"] == "JSONDecodeError"

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


def make_text_pdf(path: Path, page_texts: list[str]) -> None:
    doc = fitz.open()
    for text in page_texts:
        page = doc.new_page()
        page.insert_text((72, 72), text)
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
    assert response["page_numbers"] == [1, 2, 3]
    assert response["naming_template"] == "{box_no:0>2}_{binder_no:0>2}_{seq:0>3}.pdf"


def test_sidecar_page_preview_returns_jpeg_data_url(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_pdf(source, 1)

    response = handle_request({"command": "page_preview", "pdf_path": str(source), "page_no": 1})

    assert response["ok"] is True
    assert response["command"] == "page_preview"
    assert response["image_data_url"].startswith("data:image/jpeg;base64,")
    assert response["page_count"] == 1


def test_sidecar_page_thumbnail_returns_compact_data_url(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_pdf(source, 2)

    response = handle_request({"command": "page_thumbnail", "pdf_path": str(source), "page_no": 2})

    assert response["ok"] is True
    assert response["command"] == "page_thumbnail"
    assert response["page_no"] == 2
    assert response["image_data_url"].startswith("data:image/jpeg;base64,")


def test_sidecar_page_text_returns_text_layer(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_pdf(source, 2)

    response = handle_request({"command": "page_text", "pdf_path": str(source), "page_no": 2})

    assert response["ok"] is True
    assert response["command"] == "page_text"
    assert response["page_no"] == 2
    assert response["has_text"] is True
    assert "Page 2" in response["text"]


def test_sidecar_search_text_returns_page_hits(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_pdf(source, 3)

    response = handle_request({"command": "search_text", "pdf_paths": [str(source)], "query": "Page 2"})

    assert response["ok"] is True
    assert response["command"] == "search_text"
    assert response["query"] == "Page 2"
    assert response["results"][0]["pdf_path"] == str(source)
    assert response["results"][0]["page_no"] == 2
    assert response["results"][0]["count"] >= 1


def test_sidecar_search_text_supports_scope_and_extended_hit_metadata(tmp_path: Path) -> None:
    current = tmp_path / "current.pdf"
    other = tmp_path / "other.pdf"
    make_text_pdf(current, ["表紙", "OCR target current"])
    make_text_pdf(other, ["OCR target other"])

    response = handle_request(
        {
            "command": "search_text",
            "pdf_paths": [str(current), str(other)],
            "query": "OCR",
            "scope": "current_pdf",
            "current_pdf": str(current),
        }
    )

    assert response["ok"] is True
    assert response["command"] == "search_text"
    assert len(response["results"]) == 1
    hit = response["results"][0]
    assert hit["pdf_path"] == str(current)
    assert hit["page_no"] == 2
    assert hit["matched_terms"] == ["OCR"]
    assert hit["has_text"] is True
    assert hit["is_current_pdf"] is True


def test_sidecar_search_highlights_returns_page_rects(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_text_pdf(source, ["OCR target line"])

    response = handle_request({"command": "search_highlights", "pdf_path": str(source), "page_no": 1, "query": "OCR"})

    assert response["ok"] is True
    assert response["command"] == "search_highlights"
    assert response["page_no"] == 1
    assert response["query"] == "OCR"
    assert response["rects"]
    assert set(response["rects"][0]) == {"x0", "y0", "x1", "y1", "page_width", "page_height"}


def test_sidecar_index_candidates_returns_keyword_based_pages(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_text_pdf(source, ["normal page", "No. 001 company document", "OCR target"])

    response = handle_request({"command": "index_candidates", "pdf_paths": [str(source)]})

    assert response["ok"] is True
    assert response["command"] == "index_candidates"
    assert response["candidates"]
    candidate = response["candidates"][0]
    assert candidate["pdf_path"] == str(source)
    assert candidate["page_no"] == 2
    assert candidate["score"] > 0
    assert "No." in candidate["reason"]
    assert "company" in candidate["snippet"]


def test_sidecar_blank_candidates_returns_json_ready_scores(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_pdf(source, 2)

    response = handle_request({"command": "blank_candidates", "pdf_path": str(source)})

    assert response["ok"] is True
    assert response["command"] == "blank_candidates"
    assert isinstance(response["candidates"], list)
    for candidate in response["candidates"]:
        assert set(candidate) == {"page_no", "score"}


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


def test_sidecar_state_save_normalizes_known_keys_and_preserves_unknown_keys(tmp_path: Path) -> None:
    state = {
        "version": 1,
        "input_paths": ["source.pdf"],
        "split_points_by_pdf": {"source.pdf": ["2", 4]},
        "current_page": 1,
        "future_client_state": {"selected_tab": "split"},
    }

    save_response = handle_request({"command": "state_save", "work_dir": str(tmp_path), "state": state})
    load_response = handle_request({"command": "state_load", "work_dir": str(tmp_path)})

    assert save_response["ok"] is True
    assert load_response["ok"] is True
    assert load_response["state"]["split_points_by_pdf"] == {"source.pdf": [2, 4]}
    assert load_response["state"]["future_client_state"] == {"selected_tab": "split"}


def test_sidecar_state_save_preserves_common_metadata_known_and_unknown_string_keys(tmp_path: Path) -> None:
    common_metadata = {
        "box_no": "01",
        "binder_no": "02",
        "note": "front desk copy",
        "custom_label": "urgent",
    }
    state = {
        "version": 1,
        "input_paths": ["source.pdf"],
        "common_metadata": common_metadata,
    }

    save_response = handle_request({"command": "state_save", "work_dir": str(tmp_path), "state": state})
    load_response = handle_request({"command": "state_load", "work_dir": str(tmp_path)})

    assert save_response["ok"] is True
    assert load_response["ok"] is True
    assert load_response["state"]["common_metadata"] == common_metadata


def test_sidecar_state_save_rejects_invalid_input_paths_without_saving(tmp_path: Path) -> None:
    response = handle_request(
        {
            "command": "state_save",
            "work_dir": str(tmp_path),
            "state": {"version": 1, "input_paths": ["source.pdf", ""]},
        }
    )

    assert response["ok"] is False
    assert response["error_type"] == "TypeError"
    assert "input_paths[1] must be a non-empty string" in response["error"]
    assert not (tmp_path / "_pdf_split_state.json").exists()


def test_sidecar_state_save_rejects_invalid_segment_metadata_without_saving(tmp_path: Path) -> None:
    response = handle_request(
        {
            "command": "state_save",
            "work_dir": str(tmp_path),
            "state": {
                "version": 1,
                "input_paths": ["source.pdf"],
                "segment_metadata": {"source.pdf#1-1": {"seq": 1}},
            },
        }
    )

    assert response["ok"] is False
    assert response["error_type"] == "TypeError"
    assert "segment_metadata metadata values must be strings" in response["error"]
    assert not (tmp_path / "_pdf_split_state.json").exists()


def test_sidecar_state_save_rejects_invalid_common_metadata_without_saving(tmp_path: Path) -> None:
    response = handle_request(
        {
            "command": "state_save",
            "work_dir": str(tmp_path),
            "state": {
                "version": 1,
                "input_paths": ["source.pdf"],
                "common_metadata": {"box_no": 1},
            },
        }
    )

    assert response["ok"] is False
    assert response["error_type"] == "TypeError"
    assert "common_metadata values must be strings" in response["error"]
    assert not (tmp_path / "_pdf_split_state.json").exists()


def test_sidecar_state_save_archives_existing_state_with_invalid_input_paths(tmp_path: Path) -> None:
    state_path = tmp_path / "_pdf_split_state.json"
    state_path.write_text(
        json.dumps({"version": 1, "input_paths": ["source.pdf", ""]}),
        encoding="utf-8",
    )

    response = handle_request(
        {
            "command": "state_save",
            "work_dir": str(tmp_path),
            "state": {"version": 1, "input_paths": ["source.pdf"], "current_page": 1},
        }
    )

    assert response["ok"] is True
    assert json.loads(state_path.read_text(encoding="utf-8")) == {
        "version": 1,
        "input_paths": ["source.pdf"],
        "current_page": 1,
    }
    assert (tmp_path / "_pdf_split_state.json.corrupt").exists()
    assert not (tmp_path / "_pdf_split_state.bak.json").exists()


def test_sidecar_state_load_archives_invalid_state_and_falls_back_to_empty(tmp_path: Path) -> None:
    state_path = tmp_path / "_pdf_split_state.json"
    state_path.write_text(json.dumps({"version": 1, "current_page": 0}), encoding="utf-8")

    response = handle_request({"command": "state_load", "work_dir": str(tmp_path)})

    assert response["ok"] is True
    assert response["state"] == {}
    assert not state_path.exists()
    assert (tmp_path / "_pdf_split_state.json.corrupt").exists()


def test_sidecar_state_load_archives_invalid_segment_metadata_and_falls_back_to_empty(tmp_path: Path) -> None:
    state_path = tmp_path / "_pdf_split_state.json"
    state_path.write_text(
        json.dumps({"version": 1, "segment_metadata": {"source.pdf#1-1": {"seq": 1}}}),
        encoding="utf-8",
    )

    response = handle_request({"command": "state_load", "work_dir": str(tmp_path)})

    assert response["ok"] is True
    assert response["state"] == {}
    assert not state_path.exists()
    assert (tmp_path / "_pdf_split_state.json.corrupt").exists()


def test_sidecar_state_load_archives_invalid_common_metadata_and_falls_back_to_empty(tmp_path: Path) -> None:
    state_path = tmp_path / "_pdf_split_state.json"
    state_path.write_text(
        json.dumps({"version": 1, "common_metadata": {"box_no": 1}}),
        encoding="utf-8",
    )

    response = handle_request({"command": "state_load", "work_dir": str(tmp_path)})

    assert response["ok"] is True
    assert response["state"] == {}
    assert not state_path.exists()
    assert (tmp_path / "_pdf_split_state.json.corrupt").exists()


def test_sidecar_state_load_partially_restores_legacy_input_paths_with_invalid_entries(tmp_path: Path) -> None:
    state_path = tmp_path / "_pdf_split_state.json"
    existing_pdf = tmp_path / "existing.pdf"
    missing_pdf = tmp_path / "missing.pdf"
    make_pdf(existing_pdf, 1)
    state_path.write_text(
        json.dumps(
            {
                "version": 1,
                "input_paths": [str(existing_pdf), "", 123, str(missing_pdf)],
                "current_page": 1,
            }
        ),
        encoding="utf-8",
    )

    response = handle_request({"command": "state_load", "work_dir": str(tmp_path)})

    assert response["ok"] is True
    assert response["state"]["input_paths"] == [str(existing_pdf), str(missing_pdf)]
    assert response["messages"] == ["missing_input_pdf"]
    assert response["missing_input_paths"] == [str(missing_pdf)]
    assert state_path.exists()
    assert not (tmp_path / "_pdf_split_state.json.corrupt").exists()


def test_sidecar_state_load_preserves_missing_input_pdf_state_with_warning(tmp_path: Path) -> None:
    missing_pdf = tmp_path / "missing.pdf"
    state = {"version": 1, "input_paths": [str(missing_pdf)], "current_page": 2}

    save_response = handle_request({"command": "state_save", "work_dir": str(tmp_path), "state": state})
    raw_saved_state = (tmp_path / "_pdf_split_state.json").read_text(encoding="utf-8")
    load_response = handle_request({"command": "state_load", "work_dir": str(tmp_path)})

    assert save_response["ok"] is True
    assert load_response["ok"] is True
    # Missing PDF paths are reported at the sidecar boundary, not filtered out of saved state.
    assert load_response["state"] == state
    assert load_response["messages"] == ["missing_input_pdf"]
    assert load_response["missing_input_paths"] == [str(missing_pdf)]
    assert (tmp_path / "_pdf_split_state.json").read_text(encoding="utf-8") == raw_saved_state


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

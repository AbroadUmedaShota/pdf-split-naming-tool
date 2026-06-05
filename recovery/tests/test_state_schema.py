from __future__ import annotations

from pathlib import Path

import pytest

from pdf_splitter_tool.state_schema import missing_input_paths, normalize_state_payload


def test_normalize_state_payload_accepts_legacy_state_without_version() -> None:
    payload = {"input_paths": ["source.pdf"], "current_page": 2}

    normalized = normalize_state_payload(payload)

    assert normalized == payload
    assert normalized is not payload


def test_normalize_state_payload_preserves_unknown_keys() -> None:
    payload = {
        "schema_version": 1,
        "input_paths": [],
        "future_client_state": {"selected_tab": "details"},
    }

    normalized = normalize_state_payload(payload)

    assert normalized["future_client_state"] == {"selected_tab": "details"}


def test_normalize_state_payload_normalizes_known_keys_without_dropping_unknown_keys() -> None:
    payload = {
        "version": 1,
        "input_paths": ["source.pdf"],
        "output_dir": "out",
        "split_points_by_pdf": {"source.pdf": [2, "4"]},
        "segment_metadata": {"source.pdf": [{"seq": "001"}]},
        "common_metadata": {"box_no": "01"},
        "current_pdf": "source.pdf",
        "current_page": 3,
        "future_client_state": {"selected_tab": "details"},
    }

    normalized = normalize_state_payload(payload)

    assert normalized["split_points_by_pdf"] == {"source.pdf": [2, 4]}
    assert normalized["future_client_state"] == {"selected_tab": "details"}


def test_missing_input_paths_reports_missing_pdfs(tmp_path: Path) -> None:
    existing_pdf = tmp_path / "existing.pdf"
    missing_pdf = tmp_path / "missing.pdf"
    existing_pdf.write_bytes(b"%PDF-1.7\n")

    paths = missing_input_paths(
        {
            "input_paths": [
                str(existing_pdf),
                str(missing_pdf),
                "",
                123,
            ]
        }
    )

    assert paths == [str(missing_pdf)]


def test_missing_input_paths_keeps_legacy_ignore_policy_for_invalid_entries(tmp_path: Path) -> None:
    missing_pdf = tmp_path / "missing.pdf"

    paths = missing_input_paths({"input_paths": [str(missing_pdf), "", 123]})

    assert paths == [str(missing_pdf)]


def test_normalize_state_payload_can_drop_invalid_input_paths_for_legacy_load() -> None:
    payload = {"input_paths": ["source.pdf", "", 123, "other.pdf"]}

    normalized = normalize_state_payload(payload, allow_invalid_input_paths=True)

    assert normalized["input_paths"] == ["source.pdf", "other.pdf"]


@pytest.mark.parametrize("payload", [None, [], "state", 1])
def test_normalize_state_payload_rejects_non_object(payload: object) -> None:
    with pytest.raises(TypeError, match="JSON object"):
        normalize_state_payload(payload)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"version": "1"}, "version must be an integer"),
        ({"input_paths": "source.pdf"}, "input_paths must be a list"),
        ({"input_paths": ["source.pdf", ""]}, r"input_paths\[1\] must be a non-empty string"),
        ({"input_paths": ["source.pdf", 123]}, r"input_paths\[1\] must be a non-empty string"),
        ({"split_points_by_pdf": []}, "split_points_by_pdf must be a JSON object"),
        ({"split_points_by_pdf": {"source.pdf": [1, "x"]}}, "must be an integer"),
        ({"split_points_by_pdf": {"source.pdf": [True]}}, "must be an integer"),
        ({"current_page": 0}, "current_page must be an integer greater than or equal to 1"),
        ({"current_page": "1"}, "current_page must be an integer"),
        ({"current_pdf": 123}, "current_pdf must be a string"),
        ({"output_dir": 123}, "output_dir must be a string"),
        ({"segment_metadata": []}, "segment_metadata must be a JSON object"),
        ({"common_metadata": []}, "common_metadata must be a JSON object"),
    ],
)
def test_normalize_state_payload_rejects_invalid_known_key_types(payload: dict[str, object], message: str) -> None:
    with pytest.raises(TypeError, match=message):
        normalize_state_payload(payload)

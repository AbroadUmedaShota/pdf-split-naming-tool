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


@pytest.mark.parametrize("payload", [None, [], "state", 1])
def test_normalize_state_payload_rejects_non_object(payload: object) -> None:
    with pytest.raises(TypeError, match="JSON object"):
        normalize_state_payload(payload)

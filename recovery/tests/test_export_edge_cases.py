from __future__ import annotations

from pathlib import Path
from typing import Any

import fitz
import pytest

from pdf_splitter_tool import sidecar
from pdf_splitter_tool.sidecar import handle_request


def make_pdf(path: Path, pages: int) -> None:
    doc = fitz.open()
    for index in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"Page {index + 1}")
    doc.save(path)
    doc.close()


def segment(source: Path, start_page: int, end_page: int, seq: str = "3") -> dict[str, Any]:
    return {
        "pdf_path": str(source),
        "start_page": start_page,
        "end_page": end_page,
        "metadata": {"box_no": "1", "binder_no": "2", "seq": seq},
    }


def pdf_text(path: Path) -> str:
    with fitz.open(path) as doc:
        return "\n".join(page.get_text() for page in doc)


def assert_no_pdfs(path: Path) -> None:
    assert not path.exists() or list(path.glob("*.pdf")) == []


def test_sidecar_export_missing_output_dir_writes_no_pdf(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_pdf(source, 1)

    response = handle_request(
        {
            "command": "export",
            "output_dir": "",
            "segments": [segment(source, 1, 1)],
        }
    )

    assert response["ok"] is False
    assert response["summary"] == {"created": 0, "failed": 0}
    assert response["items"] == []
    assert response["messages"] == ["missing_output_dir"]
    assert_no_pdfs(tmp_path / "output")


def test_sidecar_export_without_segments_writes_no_pdf(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"

    response = handle_request({"command": "export", "output_dir": str(output_dir), "segments": []})

    assert response["ok"] is False
    assert response["summary"] == {"created": 0, "failed": 0}
    assert response["items"] == []
    assert response["messages"] == ["no_segments"]
    assert_no_pdfs(output_dir)


def test_sidecar_export_preflight_invalid_writes_no_pdf(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    output_dir = tmp_path / "output"
    make_pdf(source, 1)

    response = handle_request(
        {
            "command": "export",
            "output_dir": str(output_dir),
            "segments": [segment(source, 1, 2)],
        }
    )

    assert response["ok"] is False
    assert response["summary"] == {"created": 0, "failed": 1}
    assert response["messages"] == ["preflight_failed"]
    assert response["items"][0]["status"] == "failed"
    assert "PDFは1ページ" in response["items"][0]["messages"][0]
    assert_no_pdfs(output_dir)


def test_sidecar_export_uses_final_unique_path_when_file_appears_after_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.pdf"
    output_dir = tmp_path / "output"
    make_pdf(source, 1)
    original_build_checks = sidecar._build_checks

    def build_checks_then_create_competing_file(request: dict[str, Any], checked_output_dir: Path):
        checks = original_build_checks(request, checked_output_dir)
        checked_output_dir.mkdir(parents=True, exist_ok=True)
        (checked_output_dir / "01_02_003.pdf").write_bytes(b"created after preflight")
        return checks

    monkeypatch.setattr(sidecar, "_build_checks", build_checks_then_create_competing_file)

    response = handle_request(
        {
            "command": "export",
            "output_dir": str(output_dir),
            "segments": [segment(source, 1, 1)],
        }
    )

    first_path = output_dir / "01_02_003.pdf"
    escaped_path = output_dir / "01_02_003_2.pdf"
    assert response["ok"] is True
    assert response["summary"] == {"created": 1, "failed": 0}
    assert response["items"][0]["requested_filename"] == "01_02_003.pdf"
    assert Path(response["items"][0]["output_path"]) == escaped_path
    assert Path(response["items"][0]["output_path"]).name == "01_02_003_2.pdf"
    assert first_path.read_bytes() == b"created after preflight"
    assert escaped_path.exists()
    assert "Page 1" in pdf_text(escaped_path)


def test_sidecar_export_duplicate_requested_filenames_do_not_collide(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    output_dir = tmp_path / "output"
    make_pdf(source, 2)

    response = handle_request(
        {
            "command": "export",
            "output_dir": str(output_dir),
            "segments": [
                segment(source, 1, 1),
                segment(source, 2, 2),
            ],
        }
    )

    output_paths = [Path(item["output_path"]) for item in response["items"]]
    assert response["ok"] is True
    assert response["summary"] == {"created": 2, "failed": 0}
    assert [item["requested_filename"] for item in response["items"]] == ["01_02_003.pdf", "01_02_003.pdf"]
    assert [path.name for path in output_paths] == ["01_02_003.pdf", "01_02_003_2.pdf"]
    assert len(set(output_paths)) == 2
    assert "Page 1" in pdf_text(output_paths[0])
    assert "Page 2" in pdf_text(output_paths[1])

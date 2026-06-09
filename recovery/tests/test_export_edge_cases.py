from __future__ import annotations

from pathlib import Path
from typing import Any

import fitz
import pytest

from pdf_splitter_tool.pdf_service import PdfService
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


def test_sidecar_export_fails_when_reserved_output_path_appears_after_preflight(
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

    reserved_path = output_dir / "01_02_003.pdf"
    escaped_path = output_dir / "01_02_003_2.pdf"
    assert response["ok"] is False
    assert response["summary"] == {"created": 0, "failed": 1}
    assert response["items"][0]["status"] == "failed"
    assert response["items"][0]["requested_filename"] == "01_02_003.pdf"
    assert Path(response["items"][0]["output_path"]) == reserved_path
    assert response["items"][0]["error_type"] == "FileExistsError"
    assert "Output path already exists" in response["items"][0]["error"]
    assert reserved_path.read_bytes() == b"created after preflight"
    assert not escaped_path.exists()


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


def test_sidecar_preflight_and_export_block_when_existing_output_present(tmp_path: Path) -> None:
    # New behaviour: disk-level conflict => preflight can_run=False, export blocked.
    source = tmp_path / "source.pdf"
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    make_pdf(source, 2)
    existing_path = output_dir / "01_02_003.pdf"
    existing_path.write_bytes(b"existing")
    request = {
        "output_dir": str(output_dir),
        "segments": [
            segment(source, 1, 1),
            segment(source, 2, 2),
        ],
    }

    preflight_response = handle_request({"command": "preflight", **request})
    export_response = handle_request({"command": "export", **request})

    assert preflight_response["ok"] is True
    assert preflight_response["can_run"] is False
    assert any("output_exists" in check["messages"] for check in preflight_response["checks"])
    assert export_response["ok"] is False
    assert export_response["messages"] == ["preflight_failed"]
    assert export_response["summary"] == {"created": 0, "failed": 2}
    # Existing file must not be touched.
    assert existing_path.read_bytes() == b"existing"
    assert_no_pdfs(output_dir / "01_02_003_2.pdf")


def test_pdf_service_publish_file_exclusive_does_not_overwrite_existing_path(tmp_path: Path) -> None:
    source = tmp_path / "source.tmp"
    output = tmp_path / "output.pdf"
    source.write_bytes(b"new")
    output.write_bytes(b"existing")

    with pytest.raises(FileExistsError):
        PdfService.publish_file_exclusive(source, output)

    assert output.read_bytes() == b"existing"


def test_sidecar_export_partial_failure_includes_export_incomplete_in_messages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """2セグメント中1つだけ split_pdf が失敗したとき、messages に export_incomplete が含まれること。"""
    from pdf_splitter_tool.processor import PdfProcessor

    source = tmp_path / "source.pdf"
    output_dir = tmp_path / "output"
    make_pdf(source, 2)

    call_count = 0
    original_split_pdf = PdfProcessor.split_pdf

    def split_pdf_fail_on_second(seg: object, dest: object) -> object:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("simulated write failure")
        return original_split_pdf(seg, dest)

    monkeypatch.setattr(PdfProcessor, "split_pdf", staticmethod(split_pdf_fail_on_second))

    response = handle_request(
        {
            "command": "export",
            "output_dir": str(output_dir),
            "segments": [
                segment(source, 1, 1, "1"),
                segment(source, 2, 2, "2"),
            ],
        }
    )

    assert response["ok"] is False
    assert response["summary"]["created"] == 1
    assert response["summary"]["failed"] == 1
    assert "export_incomplete" in response["messages"]


def test_sidecar_export_all_success_has_empty_messages(tmp_path: Path) -> None:
    """全セグメント成功時は messages が空リストであること。"""
    source = tmp_path / "source.pdf"
    output_dir = tmp_path / "output"
    make_pdf(source, 1)

    response = handle_request(
        {
            "command": "export",
            "output_dir": str(output_dir),
            "segments": [segment(source, 1, 1)],
        }
    )

    assert response["ok"] is True
    assert response["summary"] == {"created": 1, "failed": 0}
    assert response["messages"] == []


def test_sidecar_export_all_failure_does_not_include_export_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """全セグメント失敗（created=0）のときは export_incomplete を出さないこと。"""
    from pdf_splitter_tool.processor import PdfProcessor

    source = tmp_path / "source.pdf"
    output_dir = tmp_path / "output"
    make_pdf(source, 1)

    def split_pdf_always_fail(seg: object, dest: object) -> object:
        raise RuntimeError("simulated total failure")

    monkeypatch.setattr(PdfProcessor, "split_pdf", staticmethod(split_pdf_always_fail))

    response = handle_request(
        {
            "command": "export",
            "output_dir": str(output_dir),
            "segments": [segment(source, 1, 1)],
        }
    )

    assert response["ok"] is False
    assert response["summary"]["created"] == 0
    assert response["summary"]["failed"] == 1
    assert "export_incomplete" not in response["messages"]

from __future__ import annotations

import base64
from hashlib import sha256
from pathlib import Path

import fitz

from pdf_splitter_tool.pdf_service import MAX_PREVIEW_SIDE_PX
from pdf_splitter_tool.sidecar import handle_request


def make_pdf(path: Path, page_labels: list[str], width: float = 595, height: float = 842) -> None:
    doc = fitz.open()
    for label in page_labels:
        page = doc.new_page(width=width, height=height)
        page.insert_text((72, 72), label)
    doc.save(path)
    doc.close()


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pdf_texts(path: Path) -> list[str]:
    with fitz.open(path) as doc:
        return [doc.load_page(index).get_text() for index in range(doc.page_count)]


def png_dimensions_from_data_url(data_url: str) -> tuple[int, int]:
    prefix = "data:image/png;base64,"
    assert data_url.startswith(prefix)
    pixmap = fitz.Pixmap(base64.b64decode(data_url.removeprefix(prefix), validate=True))
    return pixmap.width, pixmap.height


def test_phase12_sidecar_smoke_exports_segments_and_preserves_state(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    large_source = tmp_path / "large-source.pdf"
    output_dir = tmp_path / "output"
    work_dir = tmp_path / "work"
    make_pdf(source, ["Alpha page 1", "Bravo page 2", "Charlie page 3", "Delta page 4"])
    make_pdf(large_source, ["Large preview page"], width=10_000, height=4_000)
    segments = [
        {
            "pdf_path": str(source),
            "start_page": 1,
            "end_page": 2,
            "metadata": {"box_no": "1", "binder_no": "2", "seq": "1"},
        },
        {
            "pdf_path": str(source),
            "start_page": 3,
            "end_page": 4,
            "metadata": {"box_no": "1", "binder_no": "2", "seq": "2"},
        },
    ]

    info = handle_request({"command": "pdf_info", "pdf_path": str(source)})
    preview = handle_request({"command": "page_preview", "pdf_path": str(source), "page_no": 3})
    large_preview = handle_request({"command": "page_preview", "pdf_path": str(large_source), "page_no": 1})
    preflight = handle_request({"command": "preflight", "output_dir": str(output_dir), "segments": segments})
    export = handle_request({"command": "export", "output_dir": str(output_dir), "segments": segments})
    state_payload = {
        "version": 1,
        "input_paths": [str(source)],
        "current_page": 3,
        "output_dir": str(output_dir),
        "segments": segments,
    }
    save = handle_request({"command": "state_save", "work_dir": str(work_dir), "state": state_payload})
    load = handle_request({"command": "state_load", "work_dir": str(work_dir)})

    assert info["ok"] is True
    assert info["page_count"] == 4
    assert info["page_numbers"] == [1, 2, 3, 4]

    assert preview["ok"] is True
    assert preview["page_no"] == 3
    assert preview["image_data_url"].startswith("data:image/png;base64,")

    required_preview_keys = {"ok", "command", "pdf_path", "page_no", "page_count", "image_data_url"}
    assert required_preview_keys <= set(large_preview)
    assert large_preview["ok"] is True
    assert large_preview["command"] == "page_preview"
    assert large_preview["pdf_path"] == str(large_source)
    assert large_preview["page_no"] == 1
    assert large_preview["page_count"] == 1
    large_width, large_height = png_dimensions_from_data_url(large_preview["image_data_url"])
    assert max(large_width, large_height) <= MAX_PREVIEW_SIDE_PX

    assert preflight["ok"] is True
    assert preflight["can_run"] is True
    assert len(preflight["checks"]) == 2
    assert [check["ok"] for check in preflight["checks"]] == [True, True]
    assert [check["filename"] for check in preflight["checks"]] == ["01_02_001.pdf", "01_02_002.pdf"]
    assert [check["requested_filename"] for check in preflight["checks"]] == ["01_02_001.pdf", "01_02_002.pdf"]
    assert [check["output_path"] for check in preflight["checks"]] == [
        str(output_dir / "01_02_001.pdf"),
        str(output_dir / "01_02_002.pdf"),
    ]
    assert [check["pages"] for check in preflight["checks"]] == ["1-2", "3-4"]

    assert export["ok"] is True
    assert export["summary"] == {"created": 2, "failed": 0}
    assert [item["status"] for item in export["items"]] == ["created", "created"]
    assert [item["filename"] for item in export["items"]] == ["01_02_001.pdf", "01_02_002.pdf"]
    assert [item["pages"] for item in export["items"]] == ["1-2", "3-4"]

    first_output = output_dir / "01_02_001.pdf"
    second_output = output_dir / "01_02_002.pdf"
    assert [Path(item["output_path"]) for item in export["items"]] == [first_output, second_output]
    assert [item["sha256"] for item in export["items"]] == [file_sha256(first_output), file_sha256(second_output)]
    assert all(len(item["sha256"]) == 64 for item in export["items"])
    first_texts = pdf_texts(first_output)
    second_texts = pdf_texts(second_output)
    assert len(first_texts) == 2
    assert len(second_texts) == 2
    assert "Alpha page 1" in first_texts[0]
    assert "Bravo page 2" in first_texts[1]
    assert "Charlie page 3" in second_texts[0]
    assert "Delta page 4" in second_texts[1]

    assert save["ok"] is True
    assert load["ok"] is True
    assert load["state"] == state_payload

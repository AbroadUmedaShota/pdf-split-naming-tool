from pathlib import Path

import fitz

from pdf_splitter_tool.models import Segment
from pdf_splitter_tool.presets import YOSHIDA_ELSIS_PRESET
from pdf_splitter_tool.processor import LruCache, PdfProcessor


def make_pdf(path: Path, pages: int) -> None:
    doc = fitz.open()
    for index in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"Page {index + 1}")
    doc.save(path)
    doc.close()


def make_mixed_blank_pdf(path: Path) -> None:
    doc = fitz.open()
    doc.new_page()
    page = doc.new_page()
    page.insert_text((72, 72), "Not blank")
    doc.save(path)
    doc.close()


def test_yoshida_filename_excludes_company_and_doc() -> None:
    result = PdfProcessor.build_filename_templated(
        YOSHIDA_ELSIS_PRESET,
        {
            "box_no": "1",
            "binder_no": "2",
            "seq": "3",
            "company": "Ignored Company",
            "doc": "Ignored Document",
        },
    )

    assert result.ok
    assert result.normalized_filename == "01_02_003.pdf"


def test_yoshida_filename_requires_box_binder_seq() -> None:
    result = PdfProcessor.build_filename_templated(
        YOSHIDA_ELSIS_PRESET,
        {"box_no": "1", "binder_no": "", "seq": "3"},
    )

    assert not result.ok
    assert "missing_required:binder_no" in result.errors


def test_ensure_unique_path_adds_counter(tmp_path: Path) -> None:
    first = tmp_path / "01_02_003.pdf"
    first.write_text("existing", encoding="utf-8")

    assert PdfProcessor.ensure_unique_path(first) == tmp_path / "01_02_003_2.pdf"


def test_split_pdf_uses_one_based_inclusive_segment(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_pdf(source, 5)
    segment = Segment(source, start_page=2, end_page=4)

    output = PdfProcessor.split_pdf(segment, tmp_path / "out.pdf")

    with fitz.open(output) as doc:
        assert doc.page_count == 3
        assert "Page 2" in doc.load_page(0).get_text()
        assert "Page 4" in doc.load_page(2).get_text()


def test_lru_cache_limits_items() -> None:
    cache = LruCache(max_items=2)
    cache.set("a", 1)
    cache.set("b", 2)
    cache.get("a")
    cache.set("c", 3)

    assert len(cache) == 2
    assert cache.get("a") == 1
    assert cache.get("b") is None
    assert cache.get("c") == 3


def test_blank_page_detection(tmp_path: Path) -> None:
    source = tmp_path / "mixed.pdf"
    make_mixed_blank_pdf(source)
    processor = PdfProcessor()

    assert processor.is_blank_page(source, 1)
    assert not processor.is_blank_page(source, 2)

from pathlib import Path

import fitz

from pdf_splitter_tool.models import Segment
from pdf_splitter_tool.presets import YOSHIDA_ELSIS_PRESET
from pdf_splitter_tool.processor import LruCache, OCR_PREREQUISITE_MESSAGE, PdfProcessor


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


def make_image_only_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.draw_rect(fitz.Rect(72, 72, 180, 140), color=(0, 0, 0), fill=(0, 0, 0))
    doc.save(path)
    doc.close()


def make_blank_precision_pdf(path: Path) -> None:
    doc = fitz.open()
    doc.new_page()
    text_page = doc.new_page()
    text_page.insert_text((72, 72), "Not blank")
    line_page = doc.new_page()
    line_page.draw_line((72, 72), (520, 72), color=(0, 0, 0), width=1)
    noise_page = doc.new_page()
    for index in range(60):
        x = 72 + (index % 20) * 18
        y = 72 + (index // 20) * 24
        noise_page.draw_rect(fitz.Rect(x, y, x + 2, y + 2), color=(0.55, 0.55, 0.55), fill=(0.55, 0.55, 0.55))
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


def test_batch_text_and_index_search(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_pdf(source, 5)
    processor = PdfProcessor()

    assert processor.search_text_pages(source, "Page 3") == [3]
    assert processor.index_candidate_pages(source, ("Page 2", "Page 5")) == [2, 5]


def test_text_layer_detection_and_prerequisite_message(tmp_path: Path) -> None:
    text_pdf = tmp_path / "text.pdf"
    image_pdf = tmp_path / "image.pdf"
    make_pdf(text_pdf, 1)
    make_image_only_pdf(image_pdf)
    processor = PdfProcessor()

    assert processor.has_text_layer(text_pdf)
    assert not processor.has_text_layer(image_pdf)
    assert processor.search_text_pages(image_pdf, "Page") == []
    assert processor.extract_page_text(image_pdf, 1) == OCR_PREREQUISITE_MESSAGE


def test_search_text_rects_and_sha256(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_pdf(source, 2)

    rects = PdfProcessor.search_text_rects(source, 1, "Page")
    digest = PdfProcessor.calculate_sha256(source)

    assert rects
    assert len(digest) == 64


def test_batch_blank_detection_is_conservative(tmp_path: Path) -> None:
    source = tmp_path / "precision.pdf"
    make_blank_precision_pdf(source)
    processor = PdfProcessor()

    assert processor.blank_pages(source) == [1]


def test_batch_operations_report_progress_and_cancel(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_pdf(source, 5)
    processor = PdfProcessor()
    progress: list[tuple[int, int]] = []

    hits = processor.search_text_pages(
        source,
        "Page",
        progress=lambda current, total: progress.append((current, total)),
        cancel=lambda: len(progress) >= 2,
    )

    assert hits == [1, 2]
    assert progress[-1] == (2, 5)

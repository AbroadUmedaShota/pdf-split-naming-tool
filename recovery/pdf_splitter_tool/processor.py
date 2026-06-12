from __future__ import annotations

from pathlib import Path

from .domain import (
    DEFAULT_SEQ_DIGITS,
    METADATA_REQUIRED_KEYS,
    YOSHIDA_FILENAME_TEMPLATE,
    build_yoshida_filename_preview,
    sanitize_filename_with_warnings,
)
from .models import FilenameBuildResult, Segment
from .pdf_service import PdfService


YOSHIDA_TEMPLATE = YOSHIDA_FILENAME_TEMPLATE
REQUIRED_METADATA = METADATA_REQUIRED_KEYS


class PdfProcessor:
    @staticmethod
    def sanitize_filename(filename: str) -> tuple[str, tuple[str, ...]]:
        return sanitize_filename_with_warnings(filename)

    @staticmethod
    def build_yoshida_filename(
        metadata: dict[str, str], affix_defs: object = (), seq_digits: object = DEFAULT_SEQ_DIGITS
    ) -> FilenameBuildResult:
        return build_yoshida_filename_preview(metadata, affix_defs, seq_digits)

    @staticmethod
    def ensure_unique_path(path: Path) -> Path:
        return PdfService.ensure_unique_path(path)

    @staticmethod
    def page_count(pdf_path: Path) -> int:
        return PdfService.page_count(pdf_path)

    @staticmethod
    def page_preview_data_url(pdf_path: Path, page_no: int, zoom: float = 1.2) -> str:
        return PdfService.page_preview_data_url(pdf_path, page_no, zoom)

    @staticmethod
    def page_thumbnail_data_url(pdf_path: Path, page_no: int, zoom: float = 0.22) -> str:
        return PdfService.page_thumbnail_data_url(pdf_path, page_no, zoom)

    @staticmethod
    def page_text(pdf_path: Path, page_no: int) -> str:
        return PdfService.page_text(pdf_path, page_no)

    @staticmethod
    def search_text(
        pdf_paths: list[Path],
        query: str,
        current_pdf: Path | None = None,
        queries: list[str] | None = None,
    ) -> tuple[list[dict[str, object]], bool]:
        return PdfService.search_text(pdf_paths, query, current_pdf, queries)

    @staticmethod
    def search_highlights(pdf_path: Path, page_no: int, query: str) -> list[dict[str, float]]:
        return PdfService.search_highlights(pdf_path, page_no, query)

    @staticmethod
    def index_candidates(pdf_paths: list[Path], keywords: list[str] | None = None) -> list[dict[str, object]]:
        return PdfService.index_candidates(pdf_paths, keywords)

    @staticmethod
    def blank_candidates(
        pdf_path: Path,
        threshold: float = 0.985,
        start_page: int = 1,
    ) -> tuple[list[dict[str, object]], bool, int]:
        return PdfService.blank_candidates(pdf_path, threshold, start_page=start_page)

    @staticmethod
    def calculate_sha256(path: Path) -> str:
        return PdfService.calculate_sha256(path)

    @staticmethod
    def split_pdf(segment: Segment, output_path: Path) -> Path:
        return PdfService.split_pdf(segment, output_path)

    @staticmethod
    def build_segments_by_n_pages(pdf_path: Path, page_count: int, pages_per_segment: int) -> list[Segment]:
        if pages_per_segment < 1:
            raise ValueError("pages_per_segment must be positive.")
        segments: list[Segment] = []
        page = 1
        while page <= page_count:
            end = min(page + pages_per_segment - 1, page_count)
            segments.append(Segment(pdf_path=pdf_path, start_page=page, end_page=end))
            page = end + 1
        return segments

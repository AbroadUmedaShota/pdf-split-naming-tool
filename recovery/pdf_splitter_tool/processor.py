from __future__ import annotations

import re
import time
from collections import OrderedDict
from hashlib import sha256
from pathlib import Path
from string import Formatter
from typing import Any, Callable

from .models import FilenameBuildResult, Preset, Segment

try:
    import fitz
except Exception:  # pragma: no cover - depends on local runtime
    fitz = None


INVALID_FILENAME_CHARS = r'<>:"/\|?*'
MAX_FILENAME_LENGTH = 180
OCR_PREREQUISITE_MESSAGE = "OCR検索・転記には、事前OCR済みPDFまたはテキスト層のあるPDFを使用してください。"


class LruCache:
    def __init__(self, max_items: int) -> None:
        self.max_items = max_items
        self._items: OrderedDict[Any, Any] = OrderedDict()

    def get(self, key: Any) -> Any | None:
        if key not in self._items:
            return None
        self._items.move_to_end(key)
        return self._items[key]

    def set(self, key: Any, value: Any) -> None:
        self._items[key] = value
        self._items.move_to_end(key)
        while len(self._items) > self.max_items:
            self._items.popitem(last=False)

    def clear(self) -> None:
        self._items.clear()

    def __len__(self) -> int:
        return len(self._items)


class PdfProcessor:
    def __init__(self, preview_cache_size: int = 12, thumbnail_cache_size: int = 80) -> None:
        self.preview_cache = LruCache(preview_cache_size)
        self.thumbnail_cache = LruCache(thumbnail_cache_size)

    @staticmethod
    def sanitize_filename(filename: str) -> tuple[str, tuple[str, ...]]:
        warnings: list[str] = []
        sanitized = re.sub(f"[{re.escape(INVALID_FILENAME_CHARS)}]", "_", filename)
        sanitized = sanitized.strip().rstrip(". ")
        sanitized = re.sub(r"\s+", " ", sanitized)
        if sanitized != filename:
            warnings.append("filename_sanitized")
        if not sanitized:
            sanitized = "output.pdf"
            warnings.append("filename_empty_after_sanitize")
        return sanitized, tuple(warnings)

    @staticmethod
    def build_filename_templated(preset: Preset, metadata: dict[str, str]) -> FilenameBuildResult:
        errors: list[str] = []
        warnings: list[str] = []
        values = preset.default_metadata()
        values.update({key: str(value) for key, value in metadata.items()})

        for key in preset.required_keys():
            if not values.get(key, "").strip():
                errors.append(f"missing_required:{key}")

        template_keys = {
            field_name
            for _, field_name, _, _ in Formatter().parse(preset.naming_template)
            if field_name
        }
        missing_template_keys = [key for key in template_keys if key not in values]
        for key in missing_template_keys:
            errors.append(f"missing_template_key:{key}")

        raw = ""
        if not errors:
            try:
                raw = preset.naming_template.format(**values)
            except Exception as exc:
                errors.append(f"template_format_error:{exc}")

        if raw and not raw.lower().endswith(".pdf"):
            errors.append("template_must_end_with_pdf")

        normalized, sanitize_warnings = PdfProcessor.sanitize_filename(raw) if raw else ("", ())
        warnings.extend(sanitize_warnings)
        if normalized and len(normalized) > MAX_FILENAME_LENGTH:
            warnings.append("filename_length_warning")

        return FilenameBuildResult(
            raw_filename=raw,
            normalized_filename=normalized,
            warnings=tuple(warnings),
            errors=tuple(errors),
        )

    @staticmethod
    def ensure_unique_path(path: Path) -> Path:
        if not path.exists():
            return path
        stem = path.stem
        suffix = path.suffix
        parent = path.parent
        counter = 2
        while True:
            candidate = parent / f"{stem}_{counter}{suffix}"
            if not candidate.exists():
                return candidate
            counter += 1

    @staticmethod
    def page_count(pdf_path: Path) -> int:
        if fitz is None:
            raise RuntimeError("PyMuPDF is required for PDF operations.")
        with fitz.open(pdf_path) as doc:
            return doc.page_count

    @staticmethod
    def release_memory() -> None:
        if fitz is not None:
            try:
                fitz.TOOLS.store_shrink(100)
            except Exception:
                pass

    def render_page_pixmap(self, pdf_path: Path, page_no: int, zoom: float = 1.2):
        if fitz is None:
            raise RuntimeError("PyMuPDF is required for PDF rendering.")
        key = (str(pdf_path), page_no, zoom)
        cached = self.preview_cache.get(key)
        if cached is not None:
            return cached
        with fitz.open(pdf_path) as doc:
            page = doc.load_page(page_no - 1)
            pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        self.preview_cache.set(key, pixmap)
        return pixmap

    def render_thumbnail_pixmap(self, pdf_path: Path, page_no: int, zoom: float = 0.18):
        if fitz is None:
            raise RuntimeError("PyMuPDF is required for PDF rendering.")
        key = (str(pdf_path), page_no, zoom)
        cached = self.thumbnail_cache.get(key)
        if cached is not None:
            return cached
        with fitz.open(pdf_path) as doc:
            page = doc.load_page(page_no - 1)
            pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        self.thumbnail_cache.set(key, pixmap)
        return pixmap

    def is_blank_page(self, pdf_path: Path, page_no: int, threshold: float = 0.985) -> bool:
        if self.extract_raw_page_text(pdf_path, page_no).strip():
            return False
        pixmap = self.render_thumbnail_pixmap(pdf_path, page_no, zoom=0.12)
        return self.is_blank_pixmap(pixmap, threshold)

    @staticmethod
    def is_blank_pixmap(pixmap, threshold: float = 0.985) -> bool:
        samples = pixmap.samples
        if not samples:
            return False
        from PIL import Image

        image = Image.frombytes("RGB", (pixmap.width, pixmap.height), samples)
        histogram = image.histogram()
        channel_size = 256
        bright = 0
        dark = 0
        for offset in (0, channel_size, channel_size * 2):
            bright += sum(histogram[offset + 245 : offset + 256])
            dark += sum(histogram[offset : offset + 221])
        total = pixmap.width * pixmap.height * 3
        non_bright = total - bright
        return (
            (bright / total) >= threshold
            and (dark / total) <= 0.0002
            and (non_bright / total) <= 0.005
        )

    def search_text_pages(
        self,
        pdf_path: Path,
        query: str,
        progress: Callable[[int, int], None] | None = None,
        cancel: Callable[[], bool] | None = None,
    ) -> list[int]:
        if fitz is None:
            raise RuntimeError("PyMuPDF is required for OCR/text extraction.")
        query = query.strip().lower()
        if not query:
            return []
        if not self.has_text_layer(pdf_path):
            return []
        hits: list[int] = []
        with fitz.open(pdf_path) as doc:
            total = doc.page_count
            for index, page in enumerate(doc, start=1):
                if cancel and cancel():
                    break
                if query in page.get_text("text").lower():
                    hits.append(index)
                if progress:
                    progress(index, total)
                time.sleep(0.001)
        self.release_memory()
        return hits

    def index_candidate_pages(
        self,
        pdf_path: Path,
        keywords: tuple[str, ...],
        progress: Callable[[int, int], None] | None = None,
        cancel: Callable[[], bool] | None = None,
    ) -> list[int]:
        if fitz is None:
            raise RuntimeError("PyMuPDF is required for OCR/text extraction.")
        normalized = tuple(keyword.strip().lower() for keyword in keywords if keyword.strip())
        if not normalized:
            return []
        if not self.has_text_layer(pdf_path):
            return []
        hits: list[int] = []
        with fitz.open(pdf_path) as doc:
            total = doc.page_count
            for index, page in enumerate(doc, start=1):
                if cancel and cancel():
                    break
                text = page.get_text("text").lower()
                if any(keyword in text for keyword in normalized):
                    hits.append(index)
                if progress:
                    progress(index, total)
                time.sleep(0.001)
        self.release_memory()
        return hits

    def blank_pages(
        self,
        pdf_path: Path,
        threshold: float = 0.985,
        progress: Callable[[int, int], None] | None = None,
        cancel: Callable[[], bool] | None = None,
    ) -> list[int]:
        if fitz is None:
            raise RuntimeError("PyMuPDF is required for PDF rendering.")
        pages: list[int] = []
        with fitz.open(pdf_path) as doc:
            total = doc.page_count
            for index, page in enumerate(doc, start=1):
                if cancel and cancel():
                    break
                if not page.get_text("text").strip():
                    pixmap = page.get_pixmap(matrix=fitz.Matrix(0.12, 0.12), alpha=False)
                    self.thumbnail_cache.set((str(pdf_path), index, 0.12), pixmap)
                    if self.is_blank_pixmap(pixmap, threshold):
                        pages.append(index)
                if progress:
                    progress(index, total)
                time.sleep(0.001)
        self.release_memory()
        return pages

    @staticmethod
    def has_text_layer(pdf_path: Path, max_pages: int | None = None) -> bool:
        if fitz is None:
            raise RuntimeError("PyMuPDF is required for OCR/text extraction.")
        with fitz.open(pdf_path) as doc:
            page_count = doc.page_count if max_pages is None else min(doc.page_count, max_pages)
            for index in range(page_count):
                if doc.load_page(index).get_text("text").strip():
                    return True
        return False

    @staticmethod
    def extract_raw_page_text(pdf_path: Path, page_no: int) -> str:
        if fitz is None:
            raise RuntimeError("PyMuPDF is required for OCR/text extraction.")
        with fitz.open(pdf_path) as doc:
            return doc.load_page(page_no - 1).get_text("text")

    @staticmethod
    def extract_page_text(pdf_path: Path, page_no: int) -> str:
        text = PdfProcessor.extract_raw_page_text(pdf_path, page_no)
        if text.strip():
            return text
        return OCR_PREREQUISITE_MESSAGE

    @staticmethod
    def search_text_rects(pdf_path: Path, page_no: int, query: str) -> list[tuple[float, float, float, float]]:
        if fitz is None:
            raise RuntimeError("PyMuPDF is required for OCR/text extraction.")
        query = query.strip()
        if not query:
            return []
        with fitz.open(pdf_path) as doc:
            page = doc.load_page(page_no - 1)
            if not page.get_text("text").strip():
                return []
            return [(rect.x0, rect.y0, rect.x1, rect.y1) for rect in page.search_for(query)]

    @staticmethod
    def calculate_sha256(path: Path) -> str:
        digest = sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def split_pdf(segment: Segment, output_path: Path) -> Path:
        if fitz is None:
            raise RuntimeError("PyMuPDF is required for PDF split output.")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        final_path = PdfProcessor.ensure_unique_path(output_path)
        with fitz.open(segment.pdf_path) as src:
            with fitz.open() as dst:
                dst.insert_pdf(
                    src,
                    from_page=segment.zero_based_start,
                    to_page=segment.zero_based_end_inclusive,
                )
                dst.save(final_path)
        return final_path

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

from __future__ import annotations

import base64
import os
import shutil
from uuid import uuid4
from hashlib import sha256
from pathlib import Path

from .models import Segment

try:
    import fitz
except Exception:  # pragma: no cover - depends on local runtime
    fitz = None


MAX_PREVIEW_SIDE_PX = 2400
THUMBNAIL_ZOOM = 0.22
INDEX_CANDIDATE_KEYWORDS = ("インデックス", "目次", "表紙", "区切り", "No.", "番号", "会社名", "書類名")


class PdfService:
    @staticmethod
    def _require_fitz():
        if fitz is None:
            raise RuntimeError("PyMuPDF is required for PDF operations.")
        return fitz

    @staticmethod
    def one_based_page_to_fitz_index(page_no: int) -> int:
        page_no = int(page_no)
        if page_no < 1:
            raise ValueError("PDF page numbers are 1-based and must be positive.")
        return page_no - 1

    @staticmethod
    def one_based_range_to_fitz_indexes(page_count: int, start_page: int, end_page: int) -> tuple[int, int]:
        start_index = PdfService.one_based_page_to_fitz_index(start_page)
        end_index = PdfService.one_based_page_to_fitz_index(end_page)
        if end_index < start_index:
            raise ValueError("PDF page range end must be greater than or equal to start.")
        if end_index >= page_count:
            raise ValueError("PDF page range exceeds document page count.")
        return start_index, end_index

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
        fitz_module = PdfService._require_fitz()
        with fitz_module.open(pdf_path) as doc:
            return doc.page_count

    @staticmethod
    def _bounded_preview_zoom(page_rect, requested_zoom: float) -> float:
        max_page_side = max(float(page_rect.width), float(page_rect.height))
        requested_zoom = float(requested_zoom)
        if max_page_side <= 0:
            return requested_zoom

        max_zoom = MAX_PREVIEW_SIDE_PX / max_page_side
        return min(requested_zoom, max_zoom)

    @staticmethod
    def page_preview_data_url(pdf_path: Path, page_no: int, zoom: float = 1.2) -> str:
        fitz_module = PdfService._require_fitz()
        with fitz_module.open(pdf_path) as doc:
            page_index = PdfService.one_based_page_to_fitz_index(page_no)
            if page_index >= doc.page_count:
                raise ValueError("PDF page number exceeds document page count.")
            page = doc.load_page(page_index)
            bounded_zoom = PdfService._bounded_preview_zoom(page.rect, zoom)
            pixmap = page.get_pixmap(matrix=fitz_module.Matrix(bounded_zoom, bounded_zoom), alpha=False)
        encoded = base64.b64encode(pixmap.tobytes("png")).decode("ascii")
        return f"data:image/png;base64,{encoded}"

    @staticmethod
    def page_thumbnail_data_url(pdf_path: Path, page_no: int, zoom: float = THUMBNAIL_ZOOM) -> str:
        return PdfService.page_preview_data_url(pdf_path, page_no, zoom)

    @staticmethod
    def page_text(pdf_path: Path, page_no: int) -> str:
        fitz_module = PdfService._require_fitz()
        with fitz_module.open(pdf_path) as doc:
            page_index = PdfService.one_based_page_to_fitz_index(page_no)
            if page_index >= doc.page_count:
                raise ValueError("PDF page number exceeds document page count.")
            return doc.load_page(page_index).get_text("text").strip()

    @staticmethod
    def search_text(pdf_paths: list[Path], query: str, current_pdf: Path | None = None) -> list[dict[str, object]]:
        query = query.strip()
        if not query:
            return []

        fitz_module = PdfService._require_fitz()
        query_lower = query.lower()
        results: list[dict[str, object]] = []
        for pdf_path in pdf_paths:
            with fitz_module.open(pdf_path) as doc:
                for page_index in range(doc.page_count):
                    text = doc.load_page(page_index).get_text("text")
                    text_lower = text.lower()
                    count = text_lower.count(query_lower)
                    if count <= 0:
                        continue
                    first_index = text_lower.find(query_lower)
                    snippet_start = max(0, first_index - 28)
                    snippet_end = min(len(text), first_index + len(query) + 42)
                    snippet = " ".join(text[snippet_start:snippet_end].split())
                    results.append(
                        {
                            "pdf_path": str(pdf_path),
                            "page_no": page_index + 1,
                            "count": count,
                            "snippet": snippet,
                            "matched_terms": [query],
                            "has_text": bool(text.strip()),
                            "is_current_pdf": current_pdf is not None and pdf_path == current_pdf,
                        }
                    )
        return results

    @staticmethod
    def search_highlights(pdf_path: Path, page_no: int, query: str) -> list[dict[str, float]]:
        query = query.strip()
        if not query:
            return []

        fitz_module = PdfService._require_fitz()
        with fitz_module.open(pdf_path) as doc:
            page_index = PdfService.one_based_page_to_fitz_index(page_no)
            if page_index >= doc.page_count:
                raise ValueError("PDF page number exceeds document page count.")
            page = doc.load_page(page_index)
            page_rect = page.rect
            rects = []
            for rect in page.search_for(query):
                rects.append(
                    {
                        "x0": round(float(rect.x0), 3),
                        "y0": round(float(rect.y0), 3),
                        "x1": round(float(rect.x1), 3),
                        "y1": round(float(rect.y1), 3),
                        "page_width": round(float(page_rect.width), 3),
                        "page_height": round(float(page_rect.height), 3),
                    }
                )
            return rects

    @staticmethod
    def index_candidates(pdf_paths: list[Path], keywords: list[str] | None = None) -> list[dict[str, object]]:
        candidate_keywords = [keyword.strip() for keyword in (keywords or list(INDEX_CANDIDATE_KEYWORDS)) if keyword.strip()]
        if not candidate_keywords:
            return []

        fitz_module = PdfService._require_fitz()
        results: list[dict[str, object]] = []
        for pdf_path in pdf_paths:
            with fitz_module.open(pdf_path) as doc:
                for page_index in range(doc.page_count):
                    text = doc.load_page(page_index).get_text("text")
                    if not text.strip():
                        continue
                    text_lower = text.lower()
                    matched = [keyword for keyword in candidate_keywords if keyword.lower() in text_lower]
                    if not matched:
                        continue
                    snippet = " ".join(text.split())[:120]
                    results.append(
                        {
                            "pdf_path": str(pdf_path),
                            "page_no": page_index + 1,
                            "score": round(min(1.0, len(matched) / 3), 4),
                            "reason": " / ".join(matched),
                            "snippet": snippet,
                        }
                    )
        return results

    @staticmethod
    def blank_candidates(pdf_path: Path, threshold: float = 0.985) -> list[dict[str, object]]:
        fitz_module = PdfService._require_fitz()
        candidates: list[dict[str, object]] = []
        with fitz_module.open(pdf_path) as doc:
            for page_index in range(doc.page_count):
                page = doc.load_page(page_index)
                text = page.get_text("text").strip()
                if text:
                    continue
                pixmap = page.get_pixmap(matrix=fitz_module.Matrix(0.08, 0.08), alpha=False, colorspace=fitz_module.csGRAY)
                samples = pixmap.samples
                if not samples:
                    continue
                whiteish = sum(1 for value in samples if value >= 245)
                score = whiteish / len(samples)
                if score >= threshold:
                    candidates.append({"page_no": page_index + 1, "score": round(score, 4)})
        return candidates

    @staticmethod
    def calculate_sha256(path: Path) -> str:
        digest = sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def split_pdf(segment: Segment, output_path: Path) -> Path:
        fitz_module = PdfService._require_fitz()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = output_path.with_name(f".{output_path.name}.{uuid4().hex}.tmp")
        with fitz_module.open(segment.pdf_path) as src:
            start_index, end_index = PdfService.one_based_range_to_fitz_indexes(
                src.page_count,
                segment.start_page,
                segment.end_page,
            )
            with fitz_module.open() as dst:
                dst.insert_pdf(src, from_page=start_index, to_page=end_index)
                dst.save(temp_path)
        try:
            PdfService.publish_file_exclusive(temp_path, output_path)
        finally:
            temp_path.unlink(missing_ok=True)
        return output_path

    @staticmethod
    def publish_file_exclusive(source_path: Path, output_path: Path) -> None:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        try:
            fd = os.open(output_path, flags)
        except FileExistsError as exc:
            raise FileExistsError(f"Output path already exists: {output_path}") from exc
        try:
            with os.fdopen(fd, "wb") as target, source_path.open("rb") as source:
                shutil.copyfileobj(source, target)
        except Exception:
            Path(output_path).unlink(missing_ok=True)
            raise

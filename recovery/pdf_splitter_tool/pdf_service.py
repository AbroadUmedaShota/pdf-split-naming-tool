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
    def page_preview_data_url(pdf_path: Path, page_no: int, zoom: float = 1.2) -> str:
        fitz_module = PdfService._require_fitz()
        with fitz_module.open(pdf_path) as doc:
            page_index = PdfService.one_based_page_to_fitz_index(page_no)
            if page_index >= doc.page_count:
                raise ValueError("PDF page number exceeds document page count.")
            page = doc.load_page(page_index)
            pixmap = page.get_pixmap(matrix=fitz_module.Matrix(zoom, zoom), alpha=False)
        encoded = base64.b64encode(pixmap.tobytes("png")).decode("ascii")
        return f"data:image/png;base64,{encoded}"

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

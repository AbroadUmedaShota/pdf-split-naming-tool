from __future__ import annotations

import base64
import re
from hashlib import sha256
from pathlib import Path

from .models import FilenameBuildResult, Segment

try:
    import fitz
except Exception:  # pragma: no cover - depends on local runtime
    fitz = None


INVALID_FILENAME_CHARS = r'<>:"/\|?*'
YOSHIDA_TEMPLATE = "{box_no:0>2}_{binder_no:0>2}_{seq:0>3}.pdf"

# Windows reserved device names (case-insensitive, extension-independent).
# Matching against the stem prevents CON.pdf / con.PDF / CON from reaching the OS.
_WINDOWS_RESERVED_STEMS = frozenset(
    ["CON", "PRN", "AUX", "NUL"]
    + [f"COM{n}" for n in range(1, 10)]
    + [f"LPT{n}" for n in range(1, 10)]
)
REQUIRED_METADATA = ("box_no", "binder_no", "seq")
MAX_FILENAME_LENGTH = 180


class PdfProcessor:
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
        # Reject Windows reserved device names (CON, NUL, COM1-9, LPT1-9, …).
        # Check the stem only so "CON.pdf" and "con.PDF" are both caught.
        stem = Path(sanitized).stem.upper()
        if stem in _WINDOWS_RESERVED_STEMS:
            sanitized = f"_{sanitized}"
            warnings.append("reserved_name_prefixed")
        return sanitized, tuple(warnings)

    @staticmethod
    def build_yoshida_filename(metadata: dict[str, str]) -> FilenameBuildResult:
        values = {key: str(metadata.get(key, "")).strip() for key in REQUIRED_METADATA}
        errors = [f"missing_required:{key}" for key in REQUIRED_METADATA if not values[key]]
        raw = ""
        if not errors:
            try:
                raw = YOSHIDA_TEMPLATE.format(**values)
            except Exception as exc:
                errors.append(f"template_format_error:{exc}")
        if raw and not raw.lower().endswith(".pdf"):
            errors.append("template_must_end_with_pdf")
        normalized, warnings = PdfProcessor.sanitize_filename(raw) if raw else ("", ())
        if normalized and len(normalized) > MAX_FILENAME_LENGTH:
            warnings = (*warnings, "filename_length_warning")
        return FilenameBuildResult(raw, normalized, warnings, tuple(errors))

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
    def page_preview_data_url(
        pdf_path: Path, page_no: int, zoom: float = 1.2, jpg_quality: int = 75
    ) -> tuple[str, int]:
        """Return ``(data_url, page_count)`` for *page_no* in *pdf_path*.

        Validates *page_no* against the document's actual page count and raises
        ``ValueError`` when out of range.  The image is encoded as JPEG to keep
        the payload small for scan-origin PDFs.
        """
        if fitz is None:
            raise RuntimeError("PyMuPDF is required for PDF rendering.")
        with fitz.open(pdf_path) as doc:
            page_count = doc.page_count
            if page_no < 1 or page_no > page_count:
                raise ValueError(f"page_no must be between 1 and {page_count}")
            page = doc.load_page(page_no - 1)
            pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        encoded = base64.b64encode(pixmap.tobytes("jpg", jpg_quality=jpg_quality)).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}", page_count

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
                dst.insert_pdf(src, from_page=segment.start_page - 1, to_page=segment.end_page - 1)
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

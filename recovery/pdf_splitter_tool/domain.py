from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TypeAlias

from .models import FilenameBuildResult

Metadata: TypeAlias = Mapping[str, object]

METADATA_REQUIRED_KEYS = ("box_no", "binder_no", "seq")
YOSHIDA_FILENAME_TEMPLATE = "{box_no:0>2}_{binder_no:0>2}_{seq:0>3}.pdf"
INVALID_FILENAME_CHARS = r'<>:"/\|?*'
MAX_FILENAME_LENGTH = 180


def sanitize_filename(filename: str) -> str:
    return sanitize_filename_with_warnings(filename)[0]


def sanitize_filename_with_warnings(filename: str) -> tuple[str, tuple[str, ...]]:
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


def build_yoshida_filename_preview(metadata: Metadata) -> FilenameBuildResult:
    """Build the Yoshida filename preview for the current MVP policy."""
    values = {key: str(metadata.get(key, "")) for key in METADATA_REQUIRED_KEYS}
    errors = [f"missing_required:{key}" for key in METADATA_REQUIRED_KEYS if not values[key].strip()]
    raw = ""
    if not errors:
        try:
            raw = YOSHIDA_FILENAME_TEMPLATE.format(**values)
        except Exception as exc:
            errors.append(f"template_format_error:{exc}")
    if raw and not raw.lower().endswith(".pdf"):
        errors.append("template_must_end_with_pdf")
    normalized, warnings = sanitize_filename_with_warnings(raw) if raw else ("", ())
    if normalized and len(normalized) > MAX_FILENAME_LENGTH:
        warnings = (*warnings, "filename_length_warning")
    return FilenameBuildResult(raw, normalized, warnings, tuple(errors))


build_yoshida_filename = build_yoshida_filename_preview

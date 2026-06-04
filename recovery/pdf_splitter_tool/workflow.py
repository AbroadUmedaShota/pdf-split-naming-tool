from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .models import Segment
from .processor import PdfProcessor


FIELD_LABELS = {
    "box_no": "箱No",
    "binder_no": "バインダーNo",
    "seq": "連番",
}


@dataclass(frozen=True)
class SegmentOutputCheck:
    segment: Segment
    ok: bool
    filename: str
    output_path: Path | None
    messages: tuple[str, ...]
    requested_filename: str = ""
    requested_path: Path | None = None
    existing_path: Path | None = None
    has_existing_output: bool = False


def error_messages(errors: tuple[str, ...]) -> tuple[str, ...]:
    messages: list[str] = []
    for error in errors:
        if error.startswith("missing_required:"):
            key = error.split(":", 1)[1]
            messages.append(f"{FIELD_LABELS.get(key, key)}を入力してください")
        elif error == "template_must_end_with_pdf":
            messages.append("命名テンプレートは .pdf で終わる必要があります")
        elif error.startswith("template_format_error:"):
            messages.append("命名テンプレートの形式を確認してください")
        else:
            messages.append(error)
    return tuple(messages)


def resequence_segments(segments: list[Segment], start: int = 1, step: int = 1) -> None:
    value = start
    for segment in segments:
        segment.metadata["seq"] = str(value)
        value += step


def segment_page_errors(segment: Segment, processor: PdfProcessor) -> tuple[str, ...]:
    try:
        page_count = processor.page_count(segment.pdf_path)
    except Exception as exc:
        return (f"PDFページ数を確認できません: {exc}",)
    if segment.start_page > page_count or segment.end_page > page_count:
        return (f"分割範囲に存在しないページが含まれています: {segment.page_label} (PDFは{page_count}ページ)",)
    return ()


def check_segment_outputs(
    segments: list[Segment],
    output_dir: Path,
    processor: PdfProcessor | None = None,
) -> list[SegmentOutputCheck]:
    processor = processor or PdfProcessor()
    checks: list[SegmentOutputCheck] = []
    reserved: set[Path] = set()
    for segment in segments:
        result = processor.build_yoshida_filename(segment.metadata)
        messages = [*error_messages(result.errors), *segment_page_errors(segment, processor)]
        if result.ok and not messages:
            requested_path = output_dir / result.normalized_filename
            has_existing_output = requested_path.exists()
            output_path = unique_output_path(requested_path, reserved)
            reserved.add(output_path)
            checks.append(
                SegmentOutputCheck(
                    segment=segment,
                    ok=True,
                    filename=output_path.name,
                    output_path=output_path,
                    messages=tuple(messages),
                    requested_filename=result.normalized_filename,
                    requested_path=requested_path,
                    existing_path=requested_path if has_existing_output else None,
                    has_existing_output=has_existing_output,
                )
            )
        else:
            checks.append(
                SegmentOutputCheck(
                    segment=segment,
                    ok=False,
                    filename=result.normalized_filename,
                    output_path=None,
                    messages=tuple(messages),
                    requested_filename=result.normalized_filename,
                )
            )
    return checks


def unique_output_path(path: Path, reserved: set[Path]) -> Path:
    if not path.exists() and path not in reserved:
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    counter = 2
    while True:
        candidate = parent / f"{stem}_{counter}{suffix}"
        if not candidate.exists() and candidate not in reserved:
            return candidate
        counter += 1

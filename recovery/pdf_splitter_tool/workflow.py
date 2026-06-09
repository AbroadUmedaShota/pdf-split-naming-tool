from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .domain import DEFAULT_SEQ_DIGITS, coerce_seq_digits, normalize_affix_defs
from .export_policy import ExportPathPolicy
from .export_policy import unique_output_path as policy_unique_output_path
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
    affix_defs: object = (),
    seq_digits: object = DEFAULT_SEQ_DIGITS,
) -> list[SegmentOutputCheck]:
    processor = processor or PdfProcessor()
    affix_defs = normalize_affix_defs(affix_defs)
    seq_digits = coerce_seq_digits(seq_digits)
    checks: list[SegmentOutputCheck] = []
    export_policy = ExportPathPolicy()
    for segment in segments:
        result = processor.build_yoshida_filename(segment.metadata, affix_defs, seq_digits)
        messages = [*error_messages(result.errors), *segment_page_errors(segment, processor)]
        if result.ok and not messages:
            requested_path = output_dir / result.normalized_filename
            has_existing_output = requested_path.exists()
            if has_existing_output:
                # Disk-level conflict: block with ok=False. No path is reserved so
                # sibling segments are not affected by this slot.
                checks.append(
                    SegmentOutputCheck(
                        segment=segment,
                        ok=False,
                        filename=result.normalized_filename,
                        output_path=None,
                        messages=("output_exists",),
                        requested_filename=result.normalized_filename,
                        requested_path=requested_path,
                        existing_path=requested_path,
                        has_existing_output=True,
                    )
                )
            else:
                # No disk conflict. Reserve within the current batch to avoid
                # intra-batch duplicate names (reserved set, not disk-level).
                output_path = export_policy.reserve_output_path(requested_path)
                checks.append(
                    SegmentOutputCheck(
                        segment=segment,
                        ok=True,
                        filename=output_path.name,
                        output_path=output_path,
                        messages=tuple(messages),
                        requested_filename=result.normalized_filename,
                        requested_path=requested_path,
                        existing_path=None,
                        has_existing_output=False,
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
    return policy_unique_output_path(path, reserved)

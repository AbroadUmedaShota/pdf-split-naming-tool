from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .models import Preset, Segment
from .processor import PdfProcessor


@dataclass(frozen=True)
class SegmentOutputCheck:
    segment: Segment
    ok: bool
    filename: str
    output_path: Path | None
    messages: tuple[str, ...]


def error_messages(preset: Preset, errors: tuple[str, ...]) -> tuple[str, ...]:
    labels = {field.key: field.label for field in preset.fields}
    messages: list[str] = []
    for error in errors:
        if error.startswith("missing_required:"):
            key = error.split(":", 1)[1]
            messages.append(f"{labels.get(key, key)}を入力してください")
        elif error.startswith("missing_template_key:"):
            key = error.split(":", 1)[1]
            messages.append(f"命名テンプレートの項目 {key} が入力項目にありません")
        elif error == "template_must_end_with_pdf":
            messages.append("命名テンプレートは .pdf で終わる必要があります")
        elif error.startswith("template_format_error:"):
            messages.append("命名テンプレートの形式を確認してください")
        else:
            messages.append(error)
    return tuple(messages)


def apply_common_metadata(segments: list[Segment], metadata: dict[str, str], overwrite: bool = True) -> None:
    for segment in segments:
        for key, value in metadata.items():
            if overwrite or not segment.metadata.get(key, "").strip():
                segment.metadata[key] = value


def resequence_segments(segments: list[Segment], key: str = "seq", start: int = 1, step: int = 1) -> None:
    value = start
    for segment in segments:
        segment.metadata[key] = str(value)
        value += step


def check_segment_outputs(
    segments: list[Segment],
    preset: Preset,
    output_dir: Path,
    processor: PdfProcessor | None = None,
) -> list[SegmentOutputCheck]:
    processor = processor or PdfProcessor()
    checks: list[SegmentOutputCheck] = []
    reserved: set[Path] = set()
    for segment in segments:
        result = processor.build_filename_templated(preset, segment.metadata)
        messages = list(error_messages(preset, result.errors))
        if result.ok:
            output_path = unique_output_path(output_dir / result.normalized_filename, reserved)
            checks.append(SegmentOutputCheck(segment, True, output_path.name, output_path, tuple(messages)))
            reserved.add(output_path)
        else:
            checks.append(SegmentOutputCheck(segment, False, result.normalized_filename, None, tuple(messages)))
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

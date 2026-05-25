from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .models import Preset, Segment
from .processor import PdfProcessor

OUTPUT_ACTION_CREATE_UNIQUE = "create_unique"
OUTPUT_ACTION_REUSE_EXISTING = "reuse_existing"
OUTPUT_ACTION_SKIP = "skip"
VALID_OUTPUT_ACTIONS = {
    OUTPUT_ACTION_CREATE_UNIQUE,
    OUTPUT_ACTION_REUSE_EXISTING,
    OUTPUT_ACTION_SKIP,
}
OUTPUT_ACTION_LABELS = {
    OUTPUT_ACTION_CREATE_UNIQUE: "新規名で作成",
    OUTPUT_ACTION_REUSE_EXISTING: "既存ファイルを再利用",
    OUTPUT_ACTION_SKIP: "スキップ",
}
METADATA_SUGGESTION_VALUE_LABEL_PATTERN = (
    r"箱\s*No|箱番号|box\s*no(?![A-Za-z])|"
    r"バインダー\s*No|バインダー番号|binder\s*no(?![A-Za-z])|"
    r"連番|seq(?![A-Za-z])|番号|"
    r"会社名|company(?![A-Za-z-])|契約書名|書類名|document(?![A-Za-z-])"
)
METADATA_SUGGESTION_SEPARATOR_PATTERN = r"[:：=／/|\\\-‐‑‒–—―ー－ ]+"
METADATA_SUGGESTION_VALUE_RE = re.compile(
    rf"^\s*(?P<label>{METADATA_SUGGESTION_VALUE_LABEL_PATTERN})(?:{METADATA_SUGGESTION_SEPARATOR_PATTERN})?(?P<value>.+?)\s*$",
    re.IGNORECASE,
)
METADATA_SUGGESTION_NUMBER_LABEL_RE = re.compile(
    r"^(?:箱\s*No|箱番号|box\s*no|バインダー\s*No|バインダー番号|binder\s*no|連番|seq|番号)$",
    re.IGNORECASE,
)
METADATA_SUGGESTION_NUMBER_VALUE_RE = re.compile(r"^(?P<value>\d[\dA-Za-z_-]*)(?:\s+.+)?$")
METADATA_SUGGESTION_SHORT_NUMBER_RE = re.compile(
    r"^\s*(?:箱|バインダー)\s*(?P<value>\d[\dA-Za-z_-]*)(?:\s+.+)?\s*$",
    re.IGNORECASE,
)
METADATA_SUGGESTION_NO_VALUE_RE = re.compile(
    rf"^\s*No\.?(?:{METADATA_SUGGESTION_SEPARATOR_PATTERN})?(?P<value>\d[\dA-Za-z_-]*)(?:\s+.+)?\s*$",
    re.IGNORECASE,
)
METADATA_SUGGESTION_LEADING_MARK_RE = re.compile(r"^\s*(?:[-*•・■□◆◇●○]+|\d+[.)）])\s*")
METADATA_SUGGESTION_JAPANESE_RE = re.compile(r"[ぁ-んァ-ン一-龯]")


@dataclass(frozen=True)
class SegmentOutputCheck:
    segment: Segment
    ok: bool
    filename: str
    output_path: Path | None
    messages: tuple[str, ...]
    action: str = OUTPUT_ACTION_CREATE_UNIQUE
    requested_filename: str = ""
    requested_path: Path | None = None
    existing_path: Path | None = None
    has_existing_output: bool = False
    action_key: str = ""

    @property
    def action_label(self) -> str:
        return OUTPUT_ACTION_LABELS.get(self.action, self.action)


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


def metadata_suggestions_from_text(text: str, limit: int = 5) -> list[str]:
    labeled_values: list[str] = []
    business_lines: list[str] = []
    other_lines: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        candidate = METADATA_SUGGESTION_LEADING_MARK_RE.sub("", unicodedata.normalize("NFKC", line)).strip()
        if not candidate:
            continue
        number_match = METADATA_SUGGESTION_NO_VALUE_RE.match(candidate) or METADATA_SUGGESTION_SHORT_NUMBER_RE.match(
            candidate
        )
        value_match = None if number_match else METADATA_SUGGESTION_VALUE_RE.match(candidate)
        match = number_match or value_match
        if match:
            candidate = match.group("value").strip()
            if number_match or (
                value_match and METADATA_SUGGESTION_NUMBER_LABEL_RE.match(value_match.group("label").strip())
            ):
                number_value_match = METADATA_SUGGESTION_NUMBER_VALUE_RE.match(candidate)
                if number_value_match:
                    candidate = number_value_match.group("value")
            target = labeled_values
        elif METADATA_SUGGESTION_JAPANESE_RE.search(candidate):
            target = business_lines
        else:
            target = other_lines
        if not candidate or candidate in seen:
            continue
        target.append(candidate)
        seen.add(candidate)

    suggestions: list[str] = []
    for candidate in [*labeled_values, *business_lines, *other_lines]:
        suggestions.append(candidate)
        if len(suggestions) >= limit:
            break
    return suggestions


def check_segment_outputs(
    segments: list[Segment],
    preset: Preset,
    output_dir: Path,
    processor: PdfProcessor | None = None,
    output_actions: dict[str, str] | None = None,
) -> list[SegmentOutputCheck]:
    processor = processor or PdfProcessor()
    output_actions = output_actions or {}
    checks: list[SegmentOutputCheck] = []
    reserved: set[Path] = set()
    for segment in segments:
        result = processor.build_filename_templated(preset, segment.metadata)
        messages = list(error_messages(preset, result.errors))
        if result.ok:
            requested_path = output_dir / result.normalized_filename
            action_key = output_action_key(segment, result.normalized_filename)
            action = normalized_output_action(output_actions.get(action_key))
            has_existing_output = requested_path.exists()
            existing_path = requested_path if has_existing_output else None
            ok = True
            output_path: Path | None
            filename: str
            if action == OUTPUT_ACTION_SKIP:
                output_path = None
                filename = result.normalized_filename
            elif action == OUTPUT_ACTION_REUSE_EXISTING:
                output_path = requested_path if has_existing_output else None
                filename = result.normalized_filename
                if not has_existing_output:
                    ok = False
                    messages.append("再利用対象の既存ファイルがありません")
            else:
                output_path = unique_output_path(requested_path, reserved)
                filename = output_path.name
                reserved.add(output_path)
            checks.append(
                SegmentOutputCheck(
                    segment,
                    ok,
                    filename,
                    output_path,
                    tuple(messages),
                    action=action,
                    requested_filename=result.normalized_filename,
                    requested_path=requested_path,
                    existing_path=existing_path,
                    has_existing_output=has_existing_output,
                    action_key=action_key,
                )
            )
        else:
            checks.append(SegmentOutputCheck(segment, False, result.normalized_filename, None, tuple(messages)))
    return checks


def normalized_output_action(action: str | None) -> str:
    return action if action in VALID_OUTPUT_ACTIONS else OUTPUT_ACTION_CREATE_UNIQUE


def output_action_key(segment: Segment, filename: str) -> str:
    return f"{segment.pdf_path.resolve()}|{segment.start_page}|{segment.end_page}|{filename}"


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

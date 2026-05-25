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
    r"箱\s*No\s*\.?|箱\s*番号|box\s*(?:no\s*\.?|number)(?![A-Za-z])|"
    r"バインダー\s*No\s*\.?|バインダー\s*番号|binder\s*(?:no\s*\.?|number)(?![A-Za-z])|"
    r"連番|seq(?:uence)?\.?(?:\s*number)?(?![A-Za-z])|番号|"
    r"会社\s*名|company\s*name(?![A-Za-z-])|company(?![A-Za-z-])|"
    r"契約書\s*名|書類\s*名|(?:document|contract)\s*name(?![A-Za-z-])|document(?![A-Za-z-])"
)
METADATA_SUGGESTION_SEPARATOR_PATTERN = r"[:：=＃#／/|\\\-‐‑‒–—―ー－ ]+"
METADATA_SUGGESTION_PAREN_DECORATION_PATTERN = r"(?:[（(][^）)]*[）)])"
METADATA_SUGGESTION_SEPARATOR_ONLY_RE = re.compile(rf"^{METADATA_SUGGESTION_SEPARATOR_PATTERN}$")
METADATA_SUGGESTION_VALUE_RE = re.compile(
    rf"^\s*(?P<label>{METADATA_SUGGESTION_VALUE_LABEL_PATTERN})"
    rf"(?:{METADATA_SUGGESTION_PAREN_DECORATION_PATTERN})?"
    rf"(?:{METADATA_SUGGESTION_SEPARATOR_PATTERN})?(?P<value>.+?)\s*$",
    re.IGNORECASE,
)
METADATA_SUGGESTION_STANDALONE_LABEL_RE = re.compile(
    rf"^\s*(?P<label>{METADATA_SUGGESTION_VALUE_LABEL_PATTERN})"
    rf"(?:{METADATA_SUGGESTION_PAREN_DECORATION_PATTERN})?"
    rf"(?:{METADATA_SUGGESTION_SEPARATOR_PATTERN})?\s*$",
    re.IGNORECASE,
)
METADATA_SUGGESTION_NUMBER_LABEL_RE = re.compile(
    r"^(?:箱\s*No|箱\s*番号|box\s*no|バインダー\s*No|バインダー\s*番号|binder\s*no|連番|seq(?:uence)?\.?|番号)$",
    re.IGNORECASE,
)
METADATA_SUGGESTION_NUMBER_VALUE_RE = re.compile(
    r"^(?:(?:No\s*\.?|番号|seq(?:uence)?\.?|#)\s*)?(?P<value>\d[\dA-Za-z_-]*)(?:\s+.+)?$",
    re.IGNORECASE,
)
METADATA_SUGGESTION_SHORT_NUMBER_RE = re.compile(
    rf"^\s*(?:箱|バインダー|box|binder)(?:{METADATA_SUGGESTION_SEPARATOR_PATTERN})?(?P<value>\d[\dA-Za-z_-]*)(?:\s+.+)?\s*$",
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


def _segment_from_pages(segment: Segment, pages: list[int] | tuple[int, ...], rotations: dict[int, int] | None = None) -> Segment:
    if not pages:
        raise ValueError("Segment must contain at least one page.")
    page_numbers = tuple(int(page) for page in pages)
    planned_pages = set(page_numbers)
    planned_rotations = {page: rotation for page, rotation in dict(rotations or {}).items() if page in planned_pages}
    return Segment(
        segment.pdf_path,
        min(page_numbers),
        max(page_numbers),
        dict(segment.metadata),
        page_numbers,
        planned_rotations,
    )


def delete_segment_pages(segment: Segment, pages_to_delete: set[int]) -> Segment:
    pages = [page for page in segment.pages if page not in pages_to_delete]
    rotations = {page: rotation for page, rotation in segment.rotations.items() if page in pages}
    return _segment_from_pages(segment, pages, rotations)


def extract_segment_pages(segment: Segment, pages_to_extract: list[int] | tuple[int, ...]) -> Segment:
    available = set(segment.pages)
    pages = [page for page in pages_to_extract if page in available]
    rotations = {page: segment.rotations[page] for page in pages if page in segment.rotations}
    return _segment_from_pages(segment, pages, rotations)


def move_segment_page(segment: Segment, page_no: int, offset: int) -> Segment:
    pages = list(segment.pages)
    if page_no not in pages or offset == 0:
        return segment.copy()
    old_index = pages.index(page_no)
    page = pages.pop(old_index)
    new_index = max(0, min(len(pages), old_index + offset))
    pages.insert(new_index, page)
    return _segment_from_pages(segment, pages, dict(segment.rotations))


def rotate_segment_pages(segment: Segment, pages_to_rotate: set[int], degrees: int = 90) -> Segment:
    pages = set(segment.pages)
    rotations = dict(segment.rotations)
    for page in pages_to_rotate:
        if page in pages:
            rotations[page] = (rotations.get(page, 0) + degrees) % 360
    return _segment_from_pages(segment, segment.pages, rotations)


def segment_page_plan(segment: Segment) -> dict[str, object]:
    return {
        "source_pdf": str(segment.pdf_path),
        "pages": segment.page_label,
        "page_numbers": list(segment.pages),
        "rotations": {str(page): rotation for page, rotation in segment.rotations.items() if rotation},
    }


def segment_page_errors(segment: Segment, processor: PdfProcessor) -> tuple[str, ...]:
    seen_pages: set[int] = set()
    duplicated_pages: list[int] = []
    for page in segment.pages:
        if page in seen_pages and page not in duplicated_pages:
            duplicated_pages.append(page)
        seen_pages.add(page)
    if duplicated_pages:
        pages = ", ".join(str(page) for page in duplicated_pages)
        return (f"ページ整理に重複ページが含まれています: {pages}",)
    planned_pages = set(segment.pages)
    rotation_pages_outside_plan = sorted(page for page in segment.rotations if page not in planned_pages)
    if rotation_pages_outside_plan:
        pages = ", ".join(f"{page}ページ" for page in rotation_pages_outside_plan)
        return (f"ページ整理に対象外の回転指定が含まれています: {pages}",)
    invalid_rotations = [
        f"{page}ページ={rotation}度" for page, rotation in segment.rotations.items() if rotation % 90 != 0
    ]
    if invalid_rotations:
        return (f"ページ整理に未対応の回転角度が含まれています: {', '.join(invalid_rotations)}",)
    if not segment.page_numbers and not segment.pdf_path.exists():
        return ()
    try:
        page_count = processor.page_count(segment.pdf_path)
    except Exception as exc:
        return (f"PDFページ数を確認できません: {exc}",)
    invalid_pages = [page for page in segment.pages if page < 1 or page > page_count]
    if invalid_pages:
        pages = ", ".join(str(page) for page in invalid_pages)
        return (f"ページ整理に存在しないページが含まれています: {pages} (PDFは{page_count}ページ)",)
    return ()


def metadata_suggestion_value_from_labeled_text(candidate: str) -> str:
    standalone_label_match = METADATA_SUGGESTION_STANDALONE_LABEL_RE.match(candidate)
    if standalone_label_match:
        return candidate

    number_match = METADATA_SUGGESTION_NO_VALUE_RE.match(candidate) or METADATA_SUGGESTION_SHORT_NUMBER_RE.match(
        candidate
    )
    value_match = None if number_match else METADATA_SUGGESTION_VALUE_RE.match(candidate)
    match = number_match or value_match
    return match.group("value").strip() if match else candidate


def metadata_suggestions_from_text(text: str, limit: int = 5) -> list[str]:
    if limit <= 0:
        return []

    labeled_values: list[str] = []
    business_lines: list[str] = []
    other_lines: list[str] = []
    seen: set[str] = set()
    pending_label: str | None = None
    for line in text.splitlines():
        candidate = METADATA_SUGGESTION_LEADING_MARK_RE.sub("", unicodedata.normalize("NFKC", line)).strip()
        if not candidate:
            continue
        if pending_label:
            if METADATA_SUGGESTION_SEPARATOR_ONLY_RE.match(candidate):
                continue
            standalone_label_match = METADATA_SUGGESTION_STANDALONE_LABEL_RE.match(candidate)
            if standalone_label_match:
                pending_label = standalone_label_match.group("label").strip()
                continue
            candidate = metadata_suggestion_value_from_labeled_text(candidate)
            if METADATA_SUGGESTION_NUMBER_LABEL_RE.match(pending_label):
                number_value_match = METADATA_SUGGESTION_NUMBER_VALUE_RE.match(candidate)
                if number_value_match:
                    candidate = number_value_match.group("value")
            target = labeled_values
            pending_label = None
            if not candidate or candidate in seen:
                continue
            target.append(candidate)
            seen.add(candidate)
            continue

        standalone_label_match = METADATA_SUGGESTION_STANDALONE_LABEL_RE.match(candidate)
        if standalone_label_match:
            pending_label = standalone_label_match.group("label").strip()
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
        page_errors = segment_page_errors(segment, processor)
        messages = [*error_messages(preset, result.errors), *page_errors]
        if page_errors:
            checks.append(SegmentOutputCheck(segment, False, result.normalized_filename, None, tuple(messages)))
            continue
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
    rotations = ",".join(f"{page}:{rotation}" for page, rotation in sorted(segment.rotations.items()))
    return f"{segment.pdf_path.resolve()}|{segment.page_label}|{rotations}|{filename}"


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

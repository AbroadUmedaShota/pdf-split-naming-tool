from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .domain import DEFAULT_SEQ_DIGITS, MAX_OUTPUT_PATH_LENGTH, coerce_seq_digits, normalize_affix_defs
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
    will_overwrite: bool = False


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
    overwrite: bool = False,
    output_filenames: list[str | None] | None = None,
) -> list[SegmentOutputCheck]:
    processor = processor or PdfProcessor()
    affix_defs = normalize_affix_defs(affix_defs)
    seq_digits = coerce_seq_digits(seq_digits)
    checks: list[SegmentOutputCheck] = []
    export_policy = ExportPathPolicy()
    for index, segment in enumerate(segments):
        pinned_name = output_filenames[index] if output_filenames and index < len(output_filenames) else None
        if pinned_name:
            checks.append(
                _check_pinned_output(segment, pinned_name, output_dir, processor, export_policy, overwrite)
            )
            continue
        result = processor.build_yoshida_filename(segment.metadata, affix_defs, seq_digits)
        messages = [*error_messages(result.errors), *segment_page_errors(segment, processor)]
        if result.ok and not messages:
            requested_path = output_dir / result.normalized_filename
            path_too_long = len(str(requested_path)) >= MAX_OUTPUT_PATH_LENGTH
            has_existing_output = requested_path.exists()
            if path_too_long:
                # Full output path reaches or exceeds Windows MAX_PATH (260). Block with
                # ok=False so the user can shorten the output directory or field values
                # before attempting to export. A disk-conflict on the same path is
                # subsumed: reporting the length problem is more actionable.
                block_messages: tuple[str, ...] = ("output_path_too_long",)
                if has_existing_output:
                    block_messages = ("output_path_too_long", "output_exists")
                checks.append(
                    SegmentOutputCheck(
                        segment=segment,
                        ok=False,
                        filename=result.normalized_filename,
                        output_path=None,
                        messages=block_messages,
                        requested_filename=result.normalized_filename,
                        requested_path=requested_path,
                        existing_path=requested_path if has_existing_output else None,
                        has_existing_output=has_existing_output,
                    )
                )
            elif has_existing_output and overwrite and requested_path not in export_policy.reserved:
                # Overwrite mode: the user explicitly accepted replacing the existing
                # file with the same archival name. Reserve the exact path (no _2 rename)
                # so a sibling segment cannot also claim it within this batch.
                export_policy.reserved.add(requested_path)
                checks.append(
                    SegmentOutputCheck(
                        segment=segment,
                        ok=True,
                        filename=requested_path.name,
                        output_path=requested_path,
                        messages=("output_will_overwrite",),
                        requested_filename=result.normalized_filename,
                        requested_path=requested_path,
                        existing_path=requested_path,
                        has_existing_output=True,
                        will_overwrite=True,
                    )
                )
            elif has_existing_output and overwrite:
                # Overwrite mode, but a preceding segment in this batch already reserved
                # this exact path. Overwriting to the same archival name means the two
                # segments would write to one file (last write wins), silently dropping
                # one document while reporting created=2. Block with ok=False instead of
                # escaping to a _2 name: the overwrite intent is to keep the precise
                # archival name, so a duplicate name is a user error to fix.
                checks.append(
                    SegmentOutputCheck(
                        segment=segment,
                        ok=False,
                        filename=result.normalized_filename,
                        output_path=None,
                        messages=("duplicate_output_in_batch",),
                        requested_filename=result.normalized_filename,
                        requested_path=requested_path,
                        existing_path=requested_path,
                        has_existing_output=True,
                    )
                )
            elif has_existing_output:
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
                # No disk conflict and path length is within limits. Reserve within the
                # current batch to avoid intra-batch duplicate names (reserved set,
                # not disk-level).
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


def _check_pinned_output(
    segment: Segment,
    pinned_name: str,
    output_dir: Path,
    processor: PdfProcessor,
    export_policy: ExportPathPolicy,
    overwrite: bool,
) -> SegmentOutputCheck:
    # 確定名(output_filename)が指定された行。初回 export が既に確定した basename を
    # そのまま再利用する経路で、命名生成(build_yoshida_filename)を呼ばない。兄弟セグメントの
    # 名前を再計算で横取りする誤爆(issue #130)を構造的に防ぐため、_2 逃がしをしない。
    # ページ範囲の妥当性だけは通常どおり検証する（存在しないページの再出力を弾く）。
    page_messages = segment_page_errors(segment, processor)
    if page_messages:
        return SegmentOutputCheck(
            segment=segment,
            ok=False,
            filename=pinned_name,
            output_path=None,
            messages=tuple(page_messages),
            requested_filename=pinned_name,
        )
    # 信頼境界: 確定名は output_dir 配下の単純 basename でなければならない。パス区切りや
    # 親参照(..)を含む値はディレクトリトラバーサルの恐れがあるためブロックする。
    if not pinned_name or Path(pinned_name).name != pinned_name:
        return SegmentOutputCheck(
            segment=segment,
            ok=False,
            filename=pinned_name,
            output_path=None,
            messages=("invalid_output_filename",),
            requested_filename=pinned_name,
        )
    requested_path = output_dir / pinned_name
    path_too_long = len(str(requested_path)) >= MAX_OUTPUT_PATH_LENGTH
    has_existing_output = requested_path.exists()
    if path_too_long:
        block_messages: tuple[str, ...] = ("output_path_too_long",)
        if has_existing_output:
            block_messages = ("output_path_too_long", "output_exists")
        return SegmentOutputCheck(
            segment=segment,
            ok=False,
            filename=pinned_name,
            output_path=None,
            messages=block_messages,
            requested_filename=pinned_name,
            requested_path=requested_path,
            existing_path=requested_path if has_existing_output else None,
            has_existing_output=has_existing_output,
        )
    if requested_path in export_policy.reserved:
        # 同一バッチ内で別の行が既にこの確定名を確保済み。確定名は動かさない設計なので
        # _2 へ逃がさず、#126 と同じく duplicate_output_in_batch でブロックする。
        return SegmentOutputCheck(
            segment=segment,
            ok=False,
            filename=pinned_name,
            output_path=None,
            messages=("duplicate_output_in_batch",),
            requested_filename=pinned_name,
            requested_path=requested_path,
            existing_path=requested_path if has_existing_output else None,
            has_existing_output=has_existing_output,
        )
    if has_existing_output and not overwrite:
        # 既存ファイルがあるが上書き許可がない。確定名は動かさないため output_exists で
        # 素直にブロックする（_2 採番はしない）。
        return SegmentOutputCheck(
            segment=segment,
            ok=False,
            filename=pinned_name,
            output_path=None,
            messages=("output_exists",),
            requested_filename=pinned_name,
            requested_path=requested_path,
            existing_path=requested_path,
            has_existing_output=True,
        )
    # ここまで来たら書き込み可能。確定名スロットを予約する（同一バッチ内の確定名重複を
    # 上の reserved 判定で弾けるようにするため）。既存があれば overwrite=True の行なので
    # will_overwrite=True、無ければ新規作成。
    export_policy.reserved.add(requested_path)
    return SegmentOutputCheck(
        segment=segment,
        ok=True,
        filename=requested_path.name,
        output_path=requested_path,
        messages=("output_will_overwrite",) if has_existing_output else (),
        requested_filename=pinned_name,
        requested_path=requested_path,
        existing_path=requested_path if has_existing_output else None,
        has_existing_output=has_existing_output,
        will_overwrite=has_existing_output,
    )


def unique_output_path(path: Path, reserved: set[Path]) -> Path:
    return policy_unique_output_path(path, reserved)

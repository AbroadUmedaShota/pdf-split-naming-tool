from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .workflow import SegmentOutputCheck


@dataclass(frozen=True)
class TaggedOutputLine:
    text: str
    tag: str


@dataclass(frozen=True)
class OutputPreflightView:
    checks: list[SegmentOutputCheck]
    ready_count: int
    invalid_count: int
    summary_text: str
    status_text: str
    can_run: bool
    lines: tuple[TaggedOutputLine, ...]


def build_output_preflight_view(checks: list[SegmentOutputCheck], output_dir: Path) -> OutputPreflightView:
    ready = sum(1 for check in checks if check.ok)
    invalid = len(checks) - ready
    can_run = bool(checks) and invalid == 0
    lines: list[TaggedOutputLine] = [
        TaggedOutputLine("出力前チェックリスト\n", "heading"),
        TaggedOutputLine(f"[OK] 出力先: {output_dir}\n", "ok"),
    ]
    if checks:
        lines.append(TaggedOutputLine(f"[OK] 出力対象: {len(checks)}件\n", "ok"))
    else:
        lines.append(TaggedOutputLine("[NG] 出力対象がありません。Step 2で分割を作成してください。\n", "error"))
    if invalid:
        lines.append(TaggedOutputLine(f"[NG] 要修正: {invalid}件。Step 3で未入力や命名エラーを修正してください。\n", "error"))
    else:
        lines.append(TaggedOutputLine("[OK] 未入力・命名エラーなし\n", "ok" if checks else "warn"))
    lines.extend(
        (
            TaggedOutputLine("[OK] 同名ファイルがある場合は既存有無と処理方針を表示します。上書きは行いません。\n\n", "ok"),
            TaggedOutputLine("出力予定一覧\n", "heading"),
        )
    )
    for check in checks:
        if check.ok:
            existing = "既存あり" if check.has_existing_output else "既存なし"
            if check.action == "skip":
                tag = "warn"
                status = "スキップ"
            elif check.action == "reuse_existing":
                tag = "warn"
                status = "再利用"
            else:
                tag = "ok"
                status = "新規作成"
            lines.append(
                TaggedOutputLine(
                    f"[{status}] {check.segment.page_label} -> {check.filename} / {existing} / {check.action_label}\n",
                    tag,
                )
            )
        else:
            lines.append(
                TaggedOutputLine(
                    f"[要修正] {check.segment.page_label} -> {' / '.join(check.messages)}\n",
                    "error",
                )
            )
    return OutputPreflightView(
        checks=checks,
        ready_count=ready,
        invalid_count=invalid,
        summary_text=f"出力予定: {ready}件 / 要修正: {invalid}件 / 保存先: {output_dir}",
        status_text="出力可能" if can_run else "要修正があります",
        can_run=can_run,
        lines=tuple(lines),
    )

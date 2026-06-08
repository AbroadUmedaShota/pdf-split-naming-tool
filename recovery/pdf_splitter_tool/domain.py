from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TypeAlias

from .models import FilenameBuildResult

Metadata: TypeAlias = Mapping[str, object]
AffixDef: TypeAlias = Mapping[str, object]

METADATA_REQUIRED_KEYS = ("box_no", "binder_no", "seq")
# 箱No・バインダーNoのゼロ埋め桁数（固定）。seqの桁数はユーザー設定(seq_digits)で可変。
FIXED_TOKEN_PADS = (("box_no", 2), ("binder_no", 2))
DEFAULT_SEQ_DIGITS = 3
MIN_SEQ_DIGITS = 1
MAX_SEQ_DIGITS = 9
AFFIX_POSITIONS = ("prefix", "suffix")
MAX_AFFIX_COUNT = 2
# 参考: 旧来の固定テンプレ（追加項目なしのときの生成結果と一致する）。
YOSHIDA_FILENAME_TEMPLATE = "{box_no:0>2}_{binder_no:0>2}_{seq:0>3}.pdf"
INVALID_FILENAME_CHARS = r'<>:"/\|?*'
MAX_FILENAME_LENGTH = 180


def coerce_seq_digits(value: object, default: int = DEFAULT_SEQ_DIGITS) -> int:
    """連番のゼロ埋め桁数を [MIN_SEQ_DIGITS, MAX_SEQ_DIGITS] に正規化する。不正値は既定値。"""
    if isinstance(value, bool):
        return default
    try:
        digits = int(value)
    except (TypeError, ValueError):
        return default
    if digits < MIN_SEQ_DIGITS:
        return MIN_SEQ_DIGITS
    return min(digits, MAX_SEQ_DIGITS)


def normalize_affix_defs(raw: object) -> tuple[dict[str, str], ...]:
    """追加項目の定義列を検証して正規化する。

    各要素は {key, label, position} を持つ。無効な要素は除去し、固定3項目との
    キー衝突・重複キーを排除し、上限 MAX_AFFIX_COUNT 件までに切り詰める。
    """
    if not isinstance(raw, (list, tuple)):
        return ()
    normalized: list[dict[str, str]] = []
    seen_keys: set[str] = set()
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        key = item.get("key")
        position = item.get("position")
        if not isinstance(key, str) or not key.strip():
            continue
        key = key.strip()
        if key in METADATA_REQUIRED_KEYS or key in seen_keys:
            continue
        if position not in AFFIX_POSITIONS:
            continue
        label = item.get("label")
        label = label.strip() if isinstance(label, str) else ""
        normalized.append({"key": key, "label": label, "position": position})
        seen_keys.add(key)
        if len(normalized) >= MAX_AFFIX_COUNT:
            break
    return tuple(normalized)


def _affix_tokens(metadata: Metadata, affix_defs: object, position: str) -> list[str]:
    """指定位置(prefix/suffix)の追加項目値を定義順に返す。空値は除去する。"""
    if not affix_defs:
        return []
    tokens: list[str] = []
    for definition in affix_defs:
        if not isinstance(definition, Mapping):
            continue
        if definition.get("position") != position:
            continue
        key = definition.get("key")
        if not isinstance(key, str) or not key:
            continue
        value = str(metadata.get(key, "")).strip()
        if value:
            tokens.append(value)
    return tokens


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


def build_yoshida_filename_preview(
    metadata: Metadata, affix_defs: object = (), seq_digits: object = DEFAULT_SEQ_DIGITS,
) -> FilenameBuildResult:
    """Build the Yoshida filename preview for the current MVP policy.

    固定3項目(box_no/binder_no/seq)を必須・ゼロ埋めで並べ、任意の追加項目(affix)を
    先頭(prefix)/末尾(suffix)へ `_` 区切りで挿入する。連番(seq)のゼロ埋め桁数は
    seq_digits で指定する(既定3)。追加項目なし・seq_digits=3 のときは従来の
    `{box_no:0>2}_{binder_no:0>2}_{seq:0>3}.pdf` と完全に同一の結果になる。
    """
    digits = coerce_seq_digits(seq_digits)
    values = {key: str(metadata.get(key, "")) for key in METADATA_REQUIRED_KEYS}
    errors = [f"missing_required:{key}" for key in METADATA_REQUIRED_KEYS if not values[key].strip()]
    raw = ""
    if not errors:
        fixed_tokens = [values[key].rjust(width, "0") for key, width in FIXED_TOKEN_PADS]
        fixed_tokens.append(values["seq"].rjust(digits, "0"))
        prefixes = _affix_tokens(metadata, affix_defs, "prefix")
        suffixes = _affix_tokens(metadata, affix_defs, "suffix")
        tokens = [*prefixes, *fixed_tokens, *suffixes]
        raw = "_".join(tokens) + ".pdf"
    if raw and not raw.lower().endswith(".pdf"):
        errors.append("template_must_end_with_pdf")
    normalized, warnings = sanitize_filename_with_warnings(raw) if raw else ("", ())
    if normalized and len(normalized) > MAX_FILENAME_LENGTH:
        warnings = (*warnings, "filename_length_warning")
    return FilenameBuildResult(raw, normalized, warnings, tuple(errors))


build_yoshida_filename = build_yoshida_filename_preview

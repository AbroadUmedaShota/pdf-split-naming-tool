from __future__ import annotations

import re

from .models import MetadataField, Preset


FIELD_ROW_HELP = "key|label|required|default"
TRUE_VALUES = {"1", "true", "yes", "y", "required", "必須"}
FIELD_KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PRESET_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def parse_required(value: str) -> bool:
    return value.strip().lower() in TRUE_VALUES


def parse_field_rows(text: str) -> tuple[MetadataField, ...]:
    fields: list[MetadataField] = []
    seen: set[str] = set()
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) not in {3, 4}:
            raise ValueError(f"{line_number}行目: {FIELD_ROW_HELP} の形式で入力してください")
        key, label, required_text = parts[:3]
        default = parts[3] if len(parts) == 4 else ""
        if not FIELD_KEY_PATTERN.match(key):
            raise ValueError(f"{line_number}行目: 項目キー '{key}' は使用できません")
        if key in seen:
            raise ValueError(f"{line_number}行目: 項目キー '{key}' が重複しています")
        if not label:
            raise ValueError(f"{line_number}行目: 表示名を入力してください")
        seen.add(key)
        fields.append(MetadataField(key=key, label=label, required=parse_required(required_text), default=default))
    if not fields:
        raise ValueError("入力項目を1件以上設定してください")
    return tuple(fields)


def format_field_rows(fields: tuple[MetadataField, ...]) -> str:
    return "\n".join(
        "|".join((field.key, field.label, "true" if field.required else "false", field.default))
        for field in fields
    )


def parse_keywords(text: str) -> tuple[str, ...]:
    values: list[str] = []
    seen: set[str] = set()
    for raw in re.split(r"[\n,]", text):
        value = raw.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        values.append(value)
    return tuple(values)


def format_keywords(keywords: tuple[str, ...]) -> str:
    return ", ".join(keywords)


def validate_preset_id(preset_id: str) -> str:
    value = preset_id.strip()
    if not PRESET_ID_PATTERN.match(value):
        raise ValueError("プリセットIDは英数字、ドット、アンダースコア、ハイフンで入力してください")
    return value


def build_preset_from_editor(
    *,
    preset_id: str,
    name: str,
    field_rows: str,
    naming_template: str,
    extraction_keywords: str,
    blank_threshold: str,
    index_threshold: str,
) -> Preset:
    preset_id = validate_preset_id(preset_id)
    name = name.strip()
    if not name:
        raise ValueError("表示名を入力してください")
    naming_template = naming_template.strip()
    if not naming_template:
        raise ValueError("命名テンプレートを入力してください")
    if not naming_template.lower().endswith(".pdf"):
        raise ValueError("命名テンプレートは .pdf で終わる必要があります")
    try:
        blank_value = float(blank_threshold)
        index_value = float(index_threshold)
    except ValueError as exc:
        raise ValueError("しきい値は数値で入力してください") from exc
    if not 0 <= blank_value <= 1:
        raise ValueError("白紙しきい値は0から1の範囲で入力してください")
    if not 0 <= index_value <= 1:
        raise ValueError("インデックスしきい値は0から1の範囲で入力してください")
    return Preset(
        id=preset_id,
        name=name,
        fields=parse_field_rows(field_rows),
        naming_template=naming_template,
        extraction_keywords=parse_keywords(extraction_keywords),
        blank_threshold=blank_value,
        index_threshold=index_value,
    )

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MetadataField:
    key: str
    label: str
    required: bool = False
    input_type: str = "text"
    default: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MetadataField":
        return cls(
            key=str(data["key"]),
            label=str(data.get("label", data["key"])),
            required=bool(data.get("required", False)),
            input_type=str(data.get("input_type", "text")),
            default=str(data.get("default", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "required": self.required,
            "input_type": self.input_type,
            "default": self.default,
        }


@dataclass(frozen=True)
class Preset:
    id: str
    name: str
    fields: tuple[MetadataField, ...]
    naming_template: str
    extraction_keywords: tuple[str, ...] = ()
    blank_threshold: float = 0.985
    index_threshold: float = 0.7

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Preset":
        return cls(
            id=str(data["id"]),
            name=str(data.get("name", data["id"])),
            fields=tuple(MetadataField.from_dict(item) for item in data.get("fields", [])),
            naming_template=str(data["naming_template"]),
            extraction_keywords=tuple(str(item) for item in data.get("extraction_keywords", [])),
            blank_threshold=float(data.get("blank_threshold", 0.985)),
            index_threshold=float(data.get("index_threshold", 0.7)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "fields": [field.to_dict() for field in self.fields],
            "naming_template": self.naming_template,
            "extraction_keywords": list(self.extraction_keywords),
            "blank_threshold": self.blank_threshold,
            "index_threshold": self.index_threshold,
        }

    def default_metadata(self) -> dict[str, str]:
        return {field.key: field.default for field in self.fields}

    def required_keys(self) -> set[str]:
        return {field.key for field in self.fields if field.required}


@dataclass
class Segment:
    pdf_path: Path
    start_page: int
    end_page: int
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.start_page < 1 or self.end_page < 1:
            raise ValueError("Segment pages are 1-based and must be positive.")
        if self.end_page < self.start_page:
            raise ValueError("Segment end_page must be greater than or equal to start_page.")

    @property
    def zero_based_start(self) -> int:
        return self.start_page - 1

    @property
    def zero_based_end_inclusive(self) -> int:
        return self.end_page - 1


@dataclass
class PdfInfo:
    path: Path
    page_count: int
    common_metadata: dict[str, str] = field(default_factory=dict)
    base_seq: int = 1
    excluded_pages: set[int] = field(default_factory=set)
    last_metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class FilenameBuildResult:
    raw_filename: str
    normalized_filename: str
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors

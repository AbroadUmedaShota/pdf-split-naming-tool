from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Segment:
    pdf_path: Path
    start_page: int
    end_page: int
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.pdf_path = Path(self.pdf_path)
        self.start_page = int(self.start_page)
        self.end_page = int(self.end_page)
        self.metadata = {str(key): str(value) for key, value in self.metadata.items()}
        if self.start_page < 1 or self.end_page < 1:
            raise ValueError("Segment pages are 1-based and must be positive.")
        if self.end_page < self.start_page:
            raise ValueError("Segment end_page must be greater than or equal to start_page.")

    @property
    def pages(self) -> tuple[int, ...]:
        return tuple(range(self.start_page, self.end_page + 1))

    @property
    def page_label(self) -> str:
        return str(self.start_page) if self.start_page == self.end_page else f"{self.start_page}-{self.end_page}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "pdf_path": str(self.pdf_path),
            "start_page": self.start_page,
            "end_page": self.end_page,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Segment":
        return cls(
            Path(str(data.get("pdf_path", ""))),
            int(data.get("start_page", 1)),
            int(data.get("end_page", 1)),
            {str(key): str(value) for key, value in dict(data.get("metadata", {})).items()},
        )


@dataclass(frozen=True)
class FilenameBuildResult:
    raw_filename: str
    normalized_filename: str
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors

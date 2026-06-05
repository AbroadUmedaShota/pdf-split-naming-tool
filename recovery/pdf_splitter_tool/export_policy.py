from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


def unique_output_path(path: Path, reserved: set[Path] | None = None) -> Path:
    reserved_paths = reserved or set()
    if not path.exists() and path not in reserved_paths:
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    counter = 2
    while True:
        candidate = parent / f"{stem}_{counter}{suffix}"
        if not candidate.exists() and candidate not in reserved_paths:
            return candidate
        counter += 1


@dataclass
class ExportPathPolicy:
    reserved: set[Path] = field(default_factory=set)

    def reserve_output_path(self, requested_path: Path) -> Path:
        output_path = unique_output_path(requested_path, self.reserved)
        self.reserved.add(output_path)
        return output_path

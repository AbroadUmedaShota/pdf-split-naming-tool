from __future__ import annotations

from pathlib import Path
from typing import Any


CURRENT_SCHEMA_VERSION = 1


def normalize_state_payload(payload: object) -> dict[str, Any]:
    """Validate and return a shallow copy of a saved state payload.

    The current state file is client-owned JSON. Keep unknown keys intact so
    newer clients can round-trip through older sidecars without data loss.
    """
    if not isinstance(payload, dict):
        raise TypeError("State payload must be a JSON object.")
    return dict(payload)


def missing_input_paths(state: object) -> list[str]:
    payload = normalize_state_payload(state)
    input_paths = payload.get("input_paths", [])
    if not isinstance(input_paths, list):
        return []

    missing_paths: list[str] = []
    for raw_path in input_paths:
        if not isinstance(raw_path, str) or not raw_path:
            continue
        input_path = Path(raw_path)
        if not input_path.exists():
            missing_paths.append(str(input_path))
    return missing_paths

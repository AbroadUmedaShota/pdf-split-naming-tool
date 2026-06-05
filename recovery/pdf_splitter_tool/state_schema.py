from __future__ import annotations

from pathlib import Path
from typing import Any


CURRENT_SCHEMA_VERSION = 1
_KNOWN_STRING_FIELDS = {"current_pdf", "output_dir"}


def normalize_state_payload(payload: object, *, allow_invalid_input_paths: bool = False) -> dict[str, Any]:
    """Validate and return a shallow copy of a saved state payload.

    The current state file is client-owned JSON. Keep unknown keys intact so
    newer clients can round-trip through older sidecars without data loss.
    """
    if not isinstance(payload, dict):
        raise TypeError("State payload must be a JSON object.")
    normalized = dict(payload)

    if "version" in normalized:
        normalized["version"] = _require_int("version", normalized["version"])
    if "input_paths" in normalized:
        normalized["input_paths"] = _normalize_input_paths(
            normalized["input_paths"], allow_invalid_entries=allow_invalid_input_paths
        )
    if "split_points_by_pdf" in normalized:
        normalized["split_points_by_pdf"] = _normalize_split_points_by_pdf(normalized["split_points_by_pdf"])
    if "current_page" in normalized:
        current_page = _require_int("current_page", normalized["current_page"])
        if current_page < 1:
            raise TypeError("current_page must be an integer greater than or equal to 1.")
        normalized["current_page"] = current_page
    for field in _KNOWN_STRING_FIELDS:
        if field in normalized and not isinstance(normalized[field], str):
            raise TypeError(f"{field} must be a string.")
    if "segment_metadata" in normalized:
        normalized["segment_metadata"] = _normalize_segment_metadata(normalized["segment_metadata"])
    if "common_metadata" in normalized:
        normalized["common_metadata"] = _normalize_common_metadata(normalized["common_metadata"])

    return normalized


def _require_int(field: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be an integer.")
    return value


def _normalize_input_paths(value: object, *, allow_invalid_entries: bool) -> list[str]:
    if not isinstance(value, list):
        raise TypeError("input_paths must be a list of strings.")
    normalized: list[str] = []
    for index, raw_path in enumerate(value):
        if not isinstance(raw_path, str) or raw_path == "":
            if allow_invalid_entries:
                continue
            raise TypeError(f"input_paths[{index}] must be a non-empty string.")
        normalized.append(raw_path)
    return normalized


def _normalize_split_points_by_pdf(value: object) -> dict[str, list[int]]:
    if not isinstance(value, dict):
        raise TypeError("split_points_by_pdf must be a JSON object.")

    normalized: dict[str, list[int]] = {}
    for raw_pdf_path, raw_points in value.items():
        if not isinstance(raw_pdf_path, str) or raw_pdf_path == "":
            raise TypeError("split_points_by_pdf keys must be non-empty strings.")
        if not isinstance(raw_points, list):
            raise TypeError("split_points_by_pdf values must be lists of integers.")
        normalized[raw_pdf_path] = [
            _normalize_split_point(raw_pdf_path, index, point) for index, point in enumerate(raw_points)
        ]
    return normalized


def _normalize_split_point(pdf_path: str, index: int, value: object) -> int:
    if isinstance(value, bool):
        raise TypeError(f"split_points_by_pdf[{pdf_path!r}][{index}] must be an integer.")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    raise TypeError(f"split_points_by_pdf[{pdf_path!r}][{index}] must be an integer.")


def _normalize_segment_metadata(value: object) -> dict[str, dict[str, str]]:
    if not isinstance(value, dict):
        raise TypeError("segment_metadata must be a JSON object.")

    normalized: dict[str, dict[str, str]] = {}
    for raw_segment_key, raw_metadata in value.items():
        if not isinstance(raw_segment_key, str) or raw_segment_key == "":
            raise TypeError("segment_metadata keys must be non-empty strings.")
        if not isinstance(raw_metadata, dict):
            raise TypeError("segment_metadata values must be JSON objects.")
        normalized[raw_segment_key] = _normalize_metadata_values("segment_metadata metadata", raw_metadata)
    return normalized


def _normalize_common_metadata(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        raise TypeError("common_metadata must be a JSON object.")
    return _normalize_metadata_values("common_metadata", value)


def _normalize_metadata_values(field: str, value: dict[object, object]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for raw_key, raw_value in value.items():
        if not isinstance(raw_key, str):
            raise TypeError(f"{field} keys must be strings.")
        if not isinstance(raw_value, str):
            raise TypeError(f"{field} values must be strings.")
        normalized[raw_key] = raw_value
    return normalized


def missing_input_paths(state: object) -> list[str]:
    if not isinstance(state, dict):
        raise TypeError("State payload must be a JSON object.")
    payload = dict(state)
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

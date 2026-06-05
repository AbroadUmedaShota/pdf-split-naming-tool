from __future__ import annotations

from pathlib import Path
from typing import Any

from .models import Segment
from .processor import PdfProcessor, YOSHIDA_TEMPLATE
from .runtime import work_dir_from_request
from .state import StateManager
from .state_schema import missing_input_paths, normalize_state_payload
from .workflow import SegmentOutputCheck, check_segment_outputs


def handle_request(request: object) -> dict[str, Any]:
    if not isinstance(request, dict):
        return _error_response("", TypeError("Sidecar request must be a JSON object."))

    command = str(request.get("command", "")).strip()
    try:
        if command == "pdf_info":
            return pdf_info(request)
        if command == "page_preview":
            return page_preview(request)
        if command == "preflight":
            return preflight(request)
        if command == "export":
            return export(request)
        if command == "state_load":
            return state_load(request)
        if command == "state_save":
            return state_save(request)
    except Exception as exc:
        return _error_response(command, exc)
    return {"ok": False, "command": command, "error": f"Unsupported sidecar command: {command}"}


def _error_response(command: str, exc: Exception) -> dict[str, Any]:
    return {
        "ok": False,
        "command": command,
        "error": str(exc),
        "error_type": type(exc).__name__,
    }


def pdf_info(request: dict[str, Any]) -> dict[str, Any]:
    pdf_path = Path(str(request.get("pdf_path", "")))
    page_count = PdfProcessor.page_count(pdf_path)
    return {
        "ok": True,
        "command": "pdf_info",
        "pdf_path": str(pdf_path),
        "page_count": page_count,
        "page_numbers": list(range(1, page_count + 1)),
        "naming_template": YOSHIDA_TEMPLATE,
    }


def page_preview(request: dict[str, Any]) -> dict[str, Any]:
    pdf_path = Path(str(request.get("pdf_path", "")))
    page_no = int(request.get("page_no", 1))
    page_count = PdfProcessor.page_count(pdf_path)
    if page_no < 1 or page_no > page_count:
        raise ValueError(f"page_no must be between 1 and {page_count}")
    return {
        "ok": True,
        "command": "page_preview",
        "pdf_path": str(pdf_path),
        "page_no": page_no,
        "page_count": page_count,
        "image_data_url": PdfProcessor.page_preview_data_url(pdf_path, page_no),
    }


def preflight(request: dict[str, Any]) -> dict[str, Any]:
    raw_output_dir = str(request.get("output_dir", "")).strip()
    output_dir = Path(raw_output_dir)
    if not raw_output_dir:
        return {
            "ok": False,
            "command": "preflight",
            "can_run": False,
            "output_dir": "",
            "messages": ["missing_output_dir"],
            "checks": [],
        }
    checks = _build_checks(request, output_dir)
    if not checks:
        return {
            "ok": False,
            "command": "preflight",
            "can_run": False,
            "output_dir": str(output_dir),
            "messages": ["no_segments"],
            "checks": [],
        }
    return {
        "ok": True,
        "command": "preflight",
        "can_run": all(check.ok for check in checks),
        "output_dir": str(output_dir),
        "messages": [],
        "checks": [_check_to_dict(check) for check in checks],
    }


def export(request: dict[str, Any]) -> dict[str, Any]:
    raw_output_dir = str(request.get("output_dir", "")).strip()
    output_dir = Path(raw_output_dir)
    summary = {"created": 0, "failed": 0}
    if not raw_output_dir:
        return {
            "ok": False,
            "command": "export",
            "output_dir": "",
            "summary": summary,
            "items": [],
            "messages": ["missing_output_dir"],
        }
    checks = _build_checks(request, output_dir)
    processor = PdfProcessor()
    if not checks:
        return {
            "ok": False,
            "command": "export",
            "output_dir": str(output_dir),
            "summary": summary,
            "items": [],
            "messages": ["no_segments"],
        }
    invalid_checks = [check for check in checks if not check.ok]
    if invalid_checks:
        items = []
        for check in checks:
            item = _check_to_dict(check)
            item["status"] = "failed"
            if check.ok:
                item["messages"] = [*item["messages"], "preflight_blocked"]
            items.append(item)
        return {
            "ok": False,
            "command": "export",
            "output_dir": str(output_dir),
            "summary": {"created": 0, "failed": len(checks)},
            "items": items,
            "messages": ["preflight_failed"],
        }
    items: list[dict[str, Any]] = []
    for check in checks:
        item = _check_to_dict(check)
        if not check.output_path:
            item["status"] = "failed"
            item["messages"] = [*item["messages"], "missing output path"]
            summary["failed"] += 1
        else:
            try:
                final_path = processor.split_pdf(check.segment, check.output_path)
                item["status"] = "created"
                item["output_path"] = str(final_path)
                item["sha256"] = processor.calculate_sha256(final_path)
                summary["created"] += 1
            except Exception as exc:
                item["status"] = "failed"
                item["error"] = str(exc)
                item["error_type"] = type(exc).__name__
                summary["failed"] += 1
        items.append(item)
    return {
        "ok": summary["failed"] == 0,
        "command": "export",
        "output_dir": str(output_dir),
        "summary": summary,
        "items": items,
    }


def state_load(request: dict[str, Any]) -> dict[str, Any]:
    work_dir = work_dir_from_request(request)
    state = StateManager(work_dir).load()
    missing_paths = missing_input_paths(state)
    response = {
        "ok": True,
        "command": "state_load",
        "work_dir": str(work_dir),
        "state": state,
    }
    if missing_paths:
        response["messages"] = ["missing_input_pdf"]
        response["missing_input_paths"] = missing_paths
    return response


def state_save(request: dict[str, Any]) -> dict[str, Any]:
    work_dir = work_dir_from_request(request)
    state = request.get("state", {})
    try:
        normalized_state = normalize_state_payload(state)
    except TypeError as exc:
        if not isinstance(state, dict):
            raise TypeError("state must be a JSON object.") from exc
        raise
    StateManager(work_dir).save(normalized_state)
    return {
        "ok": True,
        "command": "state_save",
        "work_dir": str(work_dir),
    }


def _build_checks(request: dict[str, Any], output_dir: Path) -> list[SegmentOutputCheck]:
    segments = [Segment.from_dict(item) for item in request.get("segments", []) if isinstance(item, dict)]
    return check_segment_outputs(segments, output_dir)


def _check_to_dict(check: SegmentOutputCheck) -> dict[str, Any]:
    return {
        "ok": check.ok,
        "filename": check.filename,
        "output_path": str(check.output_path) if check.output_path else "",
        "messages": list(check.messages),
        "requested_filename": check.requested_filename,
        "requested_path": str(check.requested_path) if check.requested_path else "",
        "existing_path": str(check.existing_path) if check.existing_path else "",
        "has_existing_output": check.has_existing_output,
        "metadata": dict(check.segment.metadata),
        "pages": check.segment.page_label,
        "pdf_path": str(check.segment.pdf_path),
    }

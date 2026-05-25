from __future__ import annotations

from pathlib import Path
from typing import Any

from .history import OutputHistory
from .models import Preset, Segment
from .presets import PresetRepository, YOSHIDA_ELSIS_PRESET
from .processor import PdfProcessor
from .workflow import (
    OUTPUT_ACTION_REUSE_EXISTING,
    OUTPUT_ACTION_SKIP,
    SegmentOutputCheck,
    check_segment_outputs,
    metadata_suggestions_from_text,
    segment_page_plan,
)


def handle_request(request: object) -> dict[str, Any]:
    if not isinstance(request, dict):
        return _error_response("", TypeError("Sidecar request must be a JSON object."))

    command = str(request.get("command", "")).strip()
    try:
        if command == "pdf_info":
            return pdf_info(request)
        if command == "page_text":
            return page_text(request)
        if command == "presets":
            return presets(request)
        if command == "history":
            return history(request)
        if command == "preflight":
            return preflight(request)
        if command == "export":
            return export(request)
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
    processor = PdfProcessor()
    page_count = processor.page_count(pdf_path)
    return {
        "ok": True,
        "command": "pdf_info",
        "pdf_path": str(pdf_path),
        "page_count": page_count,
        "page_numbers": list(range(1, page_count + 1)),
        "has_text_layer": processor.has_text_layer(pdf_path),
        "default_preset": YOSHIDA_ELSIS_PRESET.to_dict(),
    }


def page_text(request: dict[str, Any]) -> dict[str, Any]:
    pdf_path = Path(str(request.get("pdf_path", "")))
    page_no = int(request.get("page_no", 1))
    suggestion_limit = int(request.get("suggestion_limit", 5))
    text = PdfProcessor.extract_page_text(pdf_path, page_no)
    return {
        "ok": True,
        "command": "page_text",
        "pdf_path": str(pdf_path),
        "page_no": page_no,
        "text": text,
        "suggestions": metadata_suggestions_from_text(text, limit=suggestion_limit),
    }


def presets(request: dict[str, Any]) -> dict[str, Any]:
    work_dir = Path(str(request.get("work_dir", ".")))
    loaded_presets, active_preset_id = PresetRepository(work_dir / "presets.json").load()
    return {
        "ok": True,
        "command": "presets",
        "work_dir": str(work_dir),
        "active_preset_id": active_preset_id,
        "presets": [preset.to_dict() for preset in loaded_presets],
    }


def history(request: dict[str, Any]) -> dict[str, Any]:
    work_dir = Path(str(request.get("work_dir", ".")))
    runs = OutputHistory(work_dir).load()
    return {
        "ok": True,
        "command": "history",
        "work_dir": str(work_dir),
        "count": len(runs),
        "runs": runs,
    }


def preflight(request: dict[str, Any]) -> dict[str, Any]:
    output_dir = Path(str(request.get("output_dir", ".")))
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
    output_dir = Path(str(request.get("output_dir", ".")))
    work_dir = _work_dir_from_request(request, output_dir)
    checks = _build_checks(request, output_dir)
    processor = PdfProcessor()
    summary = {"created": 0, "reused": 0, "skipped": 0, "failed": 0}
    if not checks:
        return {
            "ok": False,
            "command": "export",
            "output_dir": str(output_dir),
            "summary": summary,
            "items": [],
            "messages": ["no_segments"],
            "history": None,
            "history_error": None,
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
            "summary": {**summary, "failed": len(checks)},
            "items": items,
            "messages": ["preflight_failed"],
            "history": None,
            "history_error": None,
        }
    items: list[dict[str, Any]] = []
    for check in checks:
        item = _check_to_dict(check)
        if not check.ok:
            item["status"] = "failed"
            summary["failed"] += 1
        elif check.action == OUTPUT_ACTION_SKIP:
            item["status"] = "skipped"
            summary["skipped"] += 1
        elif check.action == OUTPUT_ACTION_REUSE_EXISTING and check.output_path:
            item["status"] = "reused"
            item["output_path"] = str(check.output_path)
            item["sha256"] = processor.calculate_sha256(check.output_path)
            summary["reused"] += 1
        elif check.output_path:
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
        else:
            item["status"] = "failed"
            item["messages"] = [*item["messages"], "missing output path"]
            summary["failed"] += 1
        items.append(item)
    history_record: dict[str, Any] | None
    history_error: dict[str, str] | None = None
    try:
        history_record = OutputHistory(work_dir).append_run(
            summary={**summary, "success": summary["created"], "output_dir": str(output_dir)},
            items=items,
        )
    except Exception as exc:
        history_record = None
        history_error = {"error": str(exc), "error_type": type(exc).__name__}
    return {
        "ok": summary["failed"] == 0 and history_error is None,
        "command": "export",
        "output_dir": str(output_dir),
        "summary": summary,
        "items": items,
        "history": history_record,
        "history_error": history_error,
    }


def _build_checks(request: dict[str, Any], output_dir: Path) -> list[SegmentOutputCheck]:
    preset = _preset_from_request(request)
    segments = [Segment.from_dict(item) for item in request.get("segments", []) if isinstance(item, dict)]
    output_actions = {
        str(key): str(value)
        for key, value in dict(request.get("output_actions", {})).items()
    }
    return check_segment_outputs(segments, preset, output_dir, output_actions=output_actions)


def _preset_from_request(request: dict[str, Any]) -> Preset:
    preset_payload = request.get("preset")
    if isinstance(preset_payload, dict):
        return Preset.from_dict(preset_payload)
    return YOSHIDA_ELSIS_PRESET


def _work_dir_from_request(request: dict[str, Any], output_dir: Path) -> Path:
    work_dir_payload = str(request.get("work_dir", "")).strip()
    if work_dir_payload:
        return Path(work_dir_payload)
    return output_dir.parent


def _check_to_dict(check: SegmentOutputCheck) -> dict[str, Any]:
    return {
        "ok": check.ok,
        "filename": check.filename,
        "output_path": str(check.output_path) if check.output_path else "",
        "messages": list(check.messages),
        "action": check.action,
        "requested_filename": check.requested_filename,
        "requested_path": str(check.requested_path) if check.requested_path else "",
        "existing_path": str(check.existing_path) if check.existing_path else "",
        "has_existing_output": check.has_existing_output,
        "action_key": check.action_key,
        "metadata": dict(check.segment.metadata),
        "page_plan": segment_page_plan(check.segment),
    }

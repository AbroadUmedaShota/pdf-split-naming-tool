from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, TextIO

from .models import Segment
from .processor import PdfProcessor, YOSHIDA_TEMPLATE
from .runtime import work_dir_from_request
from .state import StateManager
from .workflow import SegmentOutputCheck, check_segment_outputs


def serve(stdin: TextIO, stdout: TextIO) -> None:
    """JSON Lines serve loop: read one request per line, write one response per line.

    Designed to be called with real sys.stdin/sys.stdout by __main__.py, or with
    io.StringIO instances in tests.  The loop terminates normally on stdin EOF.
    Any exception that escapes from within the loop body is caught and returned as
    a protocol-layer error response so the process never dies on a bad message.
    """
    for raw_line in stdin:
        line = raw_line.strip()
        if not line:
            continue
        request_id: int | None = None
        try:
            envelope = json.loads(line)
            if not isinstance(envelope, dict):
                raise TypeError("Envelope must be a JSON object.")
            request_id = envelope.get("id")
            payload = envelope.get("request")
            if payload is None:
                raise KeyError("Envelope missing 'request' key.")
            response_body = handle_request(payload)
        except Exception as exc:
            response_body = _error_response("", exc)
        try:
            envelope_out = json.dumps(
                {"id": request_id, "response": response_body},
                ensure_ascii=False,
                separators=(",", ":"),
            )
        except Exception as exc:
            envelope_out = json.dumps(
                {"id": request_id, "response": _error_response("", exc)},
                ensure_ascii=False,
                separators=(",", ":"),
            )
        try:
            stdout.write(envelope_out + "\n")
            stdout.flush()
        except (BrokenPipeError, OSError):
            # stdout の相手（デスクトップシェル）が切断済み。セッション終了として静かに抜ける。
            return


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
        "naming_template": YOSHIDA_TEMPLATE,
    }


def page_preview(request: dict[str, Any]) -> dict[str, Any]:
    pdf_path = Path(str(request.get("pdf_path", "")))
    page_no = int(request.get("page_no", 1))
    # page_preview_data_url opens the PDF once, validates page_no, and returns
    # (data_url, page_count) — no second open needed.
    image_data_url, page_count = PdfProcessor.page_preview_data_url(pdf_path, page_no)
    return {
        "ok": True,
        "command": "page_preview",
        "pdf_path": str(pdf_path),
        "page_no": page_no,
        "page_count": page_count,
        "image_data_url": image_data_url,
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
    return {
        "ok": True,
        "command": "state_load",
        "work_dir": str(work_dir),
        "state": state,
    }


def state_save(request: dict[str, Any]) -> dict[str, Any]:
    work_dir = work_dir_from_request(request)
    state = request.get("state", {})
    if not isinstance(state, dict):
        raise TypeError("state must be a JSON object.")
    StateManager(work_dir).save(state)
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

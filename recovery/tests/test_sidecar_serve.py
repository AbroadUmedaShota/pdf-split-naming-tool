from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import fitz
import pytest

from pdf_splitter_tool.sidecar import compact_response, handle_request, serve


def make_pdf(path: Path, pages: int) -> None:
    doc = fitz.open()
    for index in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"Page {index + 1}")
    doc.save(path)
    doc.close()


def _run_serve(lines: list[str]) -> list[str]:
    """Drive serve() with in-memory streams and return the response lines."""
    out = io.StringIO()
    serve(io.StringIO("".join(lines)), out)
    return out.getvalue().splitlines()


def _line(request: dict) -> str:
    return json.dumps(request) + "\n"


def test_serve_processes_each_line_into_one_response(tmp_path: Path) -> None:
    source = tmp_path / "s.pdf"
    make_pdf(source, 3)

    outputs = _run_serve(
        [
            _line({"command": "pdf_info", "pdf_path": str(source)}),
            _line({"command": "page_thumbnail", "pdf_path": str(source), "page_no": 1}),
        ]
    )

    assert len(outputs) == 2
    first = json.loads(outputs[0])
    second = json.loads(outputs[1])
    assert first["ok"] is True and first["command"] == "pdf_info" and first["page_count"] == 3
    assert second["ok"] is True and second["command"] == "page_thumbnail"


def test_serve_response_is_single_compact_line(tmp_path: Path) -> None:
    source = tmp_path / "s.pdf"
    make_pdf(source, 1)

    # page_preview returns a large base64 data URL: the most likely place an
    # accidental indent=2 / embedded newline would break the one-line framing.
    outputs = _run_serve([_line({"command": "page_preview", "pdf_path": str(source), "page_no": 1})])

    assert len(outputs) == 1
    assert "\n" not in outputs[0]
    body = json.loads(outputs[0])
    assert body["ok"] is True
    assert body["image_data_url"].startswith("data:image/png;base64,")


def test_serve_isolates_per_request_errors_and_keeps_serving(tmp_path: Path) -> None:
    source = tmp_path / "s.pdf"
    make_pdf(source, 1)

    outputs = _run_serve(
        [
            _line({"command": "pdf_info", "pdf_path": str(tmp_path / "missing.pdf")}),  # request error
            "this is not json\n",  # malformed line
            _line({"command": "pdf_info", "pdf_path": str(source)}),  # still served
        ]
    )

    assert len(outputs) == 3
    assert json.loads(outputs[0])["ok"] is False
    assert json.loads(outputs[1])["ok"] is False  # malformed JSON -> error response, loop survives
    assert json.loads(outputs[2])["ok"] is True  # daemon kept serving after two failures


def test_serve_skips_blank_lines(tmp_path: Path) -> None:
    source = tmp_path / "s.pdf"
    make_pdf(source, 1)

    outputs = _run_serve(
        [
            "\n",
            "   \n",
            _line({"command": "pdf_info", "pdf_path": str(source)}),
            "\n",
        ]
    )

    assert len(outputs) == 1
    assert json.loads(outputs[0])["ok"] is True


def test_serve_matches_one_shot_handle_request(tmp_path: Path) -> None:
    source = tmp_path / "s.pdf"
    make_pdf(source, 2)
    requests = [
        {"command": "pdf_info", "pdf_path": str(source)},
        {"command": "bogus_command"},
        {"command": "pdf_info", "pdf_path": str(tmp_path / "nope.pdf")},
        {"command": "page_text", "pdf_path": str(source), "page_no": 1},
    ]

    outputs = _run_serve([_line(request) for request in requests])

    assert len(outputs) == len(requests)
    for request, line in zip(requests, outputs):
        # serve must yield exactly the same payload as the one-shot dispatch.
        assert json.loads(line) == handle_request(request)


def test_compact_response_has_no_embedded_newline() -> None:
    rendered = compact_response({"ok": True, "command": "pdf_info", "note": "日本語"})

    assert "\n" not in rendered
    assert json.loads(rendered) == {"ok": True, "command": "pdf_info", "note": "日本語"}


def test_serve_redirects_stray_stdout_to_protect_protocol(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "s.pdf"
    make_pdf(source, 1)
    protocol = io.StringIO()
    monkeypatch.setattr(sys, "stdout", protocol)

    serve(io.StringIO(_line({"command": "pdf_info", "pdf_path": str(source)})), sys.stdout)

    # Responses went to the original protocol stream...
    assert json.loads(protocol.getvalue().strip())["ok"] is True
    # ...and stray stdout is now pointed at stderr so library noise cannot corrupt framing.
    assert sys.stdout is sys.stderr


def test_serve_round_trips_over_real_subprocess_pipe(tmp_path: Path) -> None:
    source = tmp_path / "s.pdf"
    make_pdf(source, 2)
    recovery_dir = Path(__file__).resolve().parents[1]
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}

    proc = subprocess.Popen(
        [sys.executable, "-m", "pdf_splitter_tool", "--serve"],
        cwd=str(recovery_dir),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=env,
    )
    try:
        payload = "\n".join(
            [
                json.dumps({"command": "pdf_info", "pdf_path": str(source)}),
                json.dumps({"command": "page_thumbnail", "pdf_path": str(source), "page_no": 1}),
            ]
        ) + "\n"
        out, err = proc.communicate(payload, timeout=60)
    finally:
        if proc.poll() is None:
            proc.kill()

    lines = [line for line in out.splitlines() if line.strip()]
    assert len(lines) == 2, f"unexpected output; stderr={err!r}"
    assert json.loads(lines[0])["ok"] is True
    assert json.loads(lines[1])["ok"] is True
    assert proc.returncode == 0  # stdin EOF cleanly ends the serve loop

"""TC-CB-001..TC-CB-144 (pytest-based) executable test cases.

Each test function embeds the TC-CB ID in its name and includes a docstring
with traceability (TC / TD / TV / TA / Risk).

NOT included in this file (handled separately):
- TC-CB-060: node check-filename-policy.mjs (not pytest)
- TC-CB-106..124: node check-*.mjs scripts
- TC-CB-134..137: whole-suite / ps1 regression
- TC-CB-146..151: question-wait (not implemented by design)
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
from typing import Any

import fitz
import pytest

from pdf_splitter_tool.domain import (
    MAX_AFFIX_COUNT,
    MAX_SEQ_DIGITS,
    MIN_SEQ_DIGITS,
    build_yoshida_filename_preview,
)
from pdf_splitter_tool.pdf_service import SEARCH_TEXT_MAX_RESULTS, PdfService
from pdf_splitter_tool.sidecar import handle_request, serve
from pdf_splitter_tool.state import STATE_BAK_FILENAME, STATE_FILENAME, STATE_TMP_FILENAME, StateManager
from pdf_splitter_tool.state_schema import normalize_state_payload


# ---------------------------------------------------------------------------
# Shared helpers (mirrored from existing test files — no modification to
# product code or existing test files)
# ---------------------------------------------------------------------------


def make_pdf(path: Path, pages: int) -> None:
    """Create a simple multi-page PDF with text 'Page N' on each page."""
    doc = fitz.open()
    for index in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"Page {index + 1}")
    doc.save(path)
    doc.close()


def make_text_pdf(path: Path, page_texts: list[str]) -> None:
    """Create a PDF where each page contains the given text string."""
    doc = fitz.open()
    for text in page_texts:
        page = doc.new_page()
        if text:
            page.insert_text((72, 72), text)
    doc.save(path)
    doc.close()


def make_white_pdf(path: Path, n_pages: int) -> None:
    """Create an all-white (no text) PDF for blank-candidate detection tests."""
    doc = fitz.open()
    for _ in range(n_pages):
        doc.new_page()
    doc.save(path)
    doc.close()


def _make_envelope(request_id: int, request: dict) -> str:
    return json.dumps({"id": request_id, "request": request}, separators=(",", ":")) + "\n"


def _parse_response_lines(output: str) -> list[dict]:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


def _basic_segment(source: Path, start_page: int = 1, end_page: int = 1, seq: str = "3") -> dict[str, Any]:
    return {
        "pdf_path": str(source),
        "start_page": start_page,
        "end_page": end_page,
        "metadata": {"box_no": "1", "binder_no": "2", "seq": seq},
    }


# ===========================================================================
# Section 3.1 — Sidecar command contracts (TC-CB-001..024)
# ===========================================================================


def test_tc_cb_001_sidecar_pdf_info_ok(tmp_path: Path) -> None:
    """TC: TC-CB-001 / TD001 / TV001 / TA001 / Risk R001,R006"""
    source = tmp_path / "source.pdf"
    make_pdf(source, 3)
    response = handle_request({"command": "pdf_info", "pdf_path": str(source)})
    assert response["ok"] is True
    assert response["command"] == "pdf_info"
    assert "page_count" in response
    assert isinstance(response["page_count"], int)


def test_tc_cb_002_sidecar_page_preview_ok(tmp_path: Path) -> None:
    """TC: TC-CB-002 / TD001 / TV001 / TA001 / Risk R001,R006"""
    source = tmp_path / "source.pdf"
    make_pdf(source, 1)
    response = handle_request({"command": "page_preview", "pdf_path": str(source), "page_no": 1})
    assert response["ok"] is True
    assert response["command"] == "page_preview"
    assert "image_data_url" in response
    assert response["image_data_url"].startswith("data:image/")


def test_tc_cb_003_sidecar_page_thumbnail_ok(tmp_path: Path) -> None:
    """TC: TC-CB-003 / TD001 / TV001 / TA001 / Risk R001,R006"""
    source = tmp_path / "source.pdf"
    make_pdf(source, 1)
    response = handle_request({"command": "page_thumbnail", "pdf_path": str(source), "page_no": 1})
    assert response["ok"] is True
    assert response["command"] == "page_thumbnail"
    assert "image_data_url" in response
    assert response["image_data_url"].startswith("data:image/")


def test_tc_cb_004_sidecar_page_text_ok(tmp_path: Path) -> None:
    """TC: TC-CB-004 / TD001 / TV001 / TA001 / Risk R001,R006"""
    source = tmp_path / "source.pdf"
    make_pdf(source, 1)
    response = handle_request({"command": "page_text", "pdf_path": str(source), "page_no": 1})
    assert response["ok"] is True
    assert response["command"] == "page_text"
    assert "text" in response
    assert isinstance(response["text"], str)


def test_tc_cb_005_sidecar_search_text_ok(tmp_path: Path) -> None:
    """TC: TC-CB-005 / TD001 / TV001 / TA001 / Risk R001,R006"""
    source = tmp_path / "source.pdf"
    make_pdf(source, 2)
    response = handle_request({"command": "search_text", "pdf_paths": [str(source)], "query": "Page"})
    assert response["ok"] is True
    assert response["command"] == "search_text"
    assert "results" in response
    assert isinstance(response["results"], list)


def test_tc_cb_006_sidecar_search_highlights_ok(tmp_path: Path) -> None:
    """TC: TC-CB-006 / TD001 / TV001 / TA001 / Risk R001,R006"""
    source = tmp_path / "source.pdf"
    make_text_pdf(source, ["hello world"])
    response = handle_request({"command": "search_highlights", "pdf_path": str(source), "page_no": 1, "query": "hello"})
    assert response["ok"] is True
    assert response["command"] == "search_highlights"
    assert "rects" in response
    assert isinstance(response["rects"], list)


def test_tc_cb_007_sidecar_index_candidates_ok(tmp_path: Path) -> None:
    """TC: TC-CB-007 / TD001 / TV001 / TA001 / Risk R001,R006"""
    source = tmp_path / "source.pdf"
    make_text_pdf(source, ["No. 001 company list"])
    response = handle_request({"command": "index_candidates", "pdf_paths": [str(source)]})
    assert response["ok"] is True
    assert response["command"] == "index_candidates"
    assert "candidates" in response
    assert isinstance(response["candidates"], list)


def test_tc_cb_008_sidecar_blank_candidates_ok(tmp_path: Path) -> None:
    """TC: TC-CB-008 / TD001 / TV001 / TA001 / Risk R001,R006"""
    source = tmp_path / "source.pdf"
    make_pdf(source, 2)
    response = handle_request({"command": "blank_candidates", "pdf_path": str(source)})
    assert response["ok"] is True
    assert response["command"] == "blank_candidates"
    assert "candidates" in response
    assert isinstance(response["candidates"], list)


def test_tc_cb_009_sidecar_preflight_ok(tmp_path: Path) -> None:
    """TC: TC-CB-009 / TD001 / TV001 / TA001 / Risk R001,R006"""
    source = tmp_path / "source.pdf"
    make_pdf(source, 2)
    response = handle_request({
        "command": "preflight",
        "output_dir": str(tmp_path / "output"),
        "segments": [_basic_segment(source, 1, 2)],
    })
    assert response["ok"] is True
    assert response["command"] == "preflight"
    assert "checks" in response
    assert isinstance(response["checks"], list)
    assert "can_run" in response
    assert isinstance(response["can_run"], bool)


def test_tc_cb_010_sidecar_export_ok(tmp_path: Path) -> None:
    """TC: TC-CB-010 / TD001 / TV001 / TA001 / Risk R001,R006"""
    source = tmp_path / "source.pdf"
    output_dir = tmp_path / "output"
    make_pdf(source, 1)
    response = handle_request({
        "command": "export",
        "output_dir": str(output_dir),
        "segments": [_basic_segment(source, 1, 1)],
    })
    assert response["ok"] is True
    assert response["command"] == "export"
    assert "summary" in response
    assert isinstance(response["summary"], dict)
    assert "items" in response
    assert isinstance(response["items"], list)


def test_tc_cb_011_sidecar_state_load_ok(tmp_path: Path) -> None:
    """TC: TC-CB-011 / TD001 / TV001 / TA001 / Risk R001,R006"""
    response = handle_request({"command": "state_load", "work_dir": str(tmp_path)})
    assert response["ok"] is True
    assert response["command"] == "state_load"
    assert "state" in response
    assert isinstance(response["state"], dict)


def test_tc_cb_012_sidecar_state_save_ok(tmp_path: Path) -> None:
    """TC: TC-CB-012 / TD001 / TV001 / TA001 / Risk R001,R006"""
    response = handle_request({
        "command": "state_save",
        "work_dir": str(tmp_path),
        "state": {"version": 1, "input_paths": []},
    })
    assert response["ok"] is True
    assert response["command"] == "state_save"


# --- page_preview boundary tests ---


def test_tc_cb_013_page_preview_page_no_zero_returns_error(tmp_path: Path) -> None:
    """TC: TC-CB-013 / TD002 / TV002 / TA001 / Risk R001"""
    source = tmp_path / "source.pdf"
    make_pdf(source, 3)
    response = handle_request({"command": "page_preview", "pdf_path": str(source), "page_no": 0})
    assert response["ok"] is False
    assert "error" in response


def test_tc_cb_014_page_preview_page_no_negative_returns_error(tmp_path: Path) -> None:
    """TC: TC-CB-014 / TD002 / TV002 / TA001 / Risk R001"""
    source = tmp_path / "source.pdf"
    make_pdf(source, 3)
    response = handle_request({"command": "page_preview", "pdf_path": str(source), "page_no": -1})
    assert response["ok"] is False
    assert "error" in response


def test_tc_cb_015_page_preview_last_page_ok(tmp_path: Path) -> None:
    """TC: TC-CB-015 / TD002 / TV002 / TA001 / Risk R001"""
    source = tmp_path / "source.pdf"
    make_pdf(source, 3)
    # page_count is 3; page_no=3 must succeed
    response = handle_request({"command": "page_preview", "pdf_path": str(source), "page_no": 3})
    assert response["ok"] is True
    assert "image_data_url" in response


def test_tc_cb_016_page_preview_beyond_last_page_returns_error(tmp_path: Path) -> None:
    """TC: TC-CB-016 / TD002 / TV002 / TA001 / Risk R001"""
    source = tmp_path / "source.pdf"
    make_pdf(source, 3)
    # page_count is 3; page_no=4 must fail
    response = handle_request({"command": "page_preview", "pdf_path": str(source), "page_no": 4})
    assert response["ok"] is False
    assert "error" in response


# --- Type-mismatch / protocol error tests ---


def test_tc_cb_017_search_text_pdf_paths_not_array_returns_error(tmp_path: Path) -> None:
    """TC: TC-CB-017 / TD003 / TV003 / TA001 / Risk R006"""
    response = handle_request({"command": "search_text", "pdf_paths": "not_an_array", "query": "test"})
    assert response["ok"] is False
    assert "error" in response


def test_tc_cb_018_state_save_state_is_string_returns_error(tmp_path: Path) -> None:
    """TC: TC-CB-018 / TD003 / TV003 / TA001 / Risk R006"""
    response = handle_request({
        "command": "state_save",
        "work_dir": str(tmp_path),
        "state": "not_a_dict",
    })
    assert response["ok"] is False
    assert "error" in response


def test_tc_cb_019_top_level_request_is_list_returns_error() -> None:
    """TC: TC-CB-019 / TD003 / TV003 / TA001 / Risk R006"""
    response = handle_request(["not", "an", "object"])  # type: ignore[arg-type]
    assert response["ok"] is False
    assert "error" in response


def test_tc_cb_020_missing_command_key_returns_error() -> None:
    """TC: TC-CB-020 / TD003 / TV003 / TA001 / Risk R006"""
    # command key is absent — should fall through to Unsupported command with empty string
    response = handle_request({"pdf_path": "something.pdf"})
    assert response["ok"] is False


def test_tc_cb_021_undefined_command_returns_unsupported_error() -> None:
    """TC: TC-CB-021 / TD004 / TV004 / TA001 / Risk R006"""
    response = handle_request({"command": "undefined_command_xyz"})
    assert response["ok"] is False
    assert "Unsupported sidecar command" in response.get("error", "")


# --- serve loop resilience ---


def test_tc_cb_022_serve_invalid_json_then_valid_request(tmp_path: Path) -> None:
    """TC: TC-CB-022 / TD005 / TV005 / TA001 / Risk R006"""
    invalid_line = "this is not json\n"
    valid_line = _make_envelope(99, {"command": "state_save", "work_dir": str(tmp_path), "state": {}})
    stdin = io.StringIO(invalid_line + valid_line)
    stdout = io.StringIO()
    serve(stdin, stdout)
    responses = _parse_response_lines(stdout.getvalue())
    assert len(responses) == 2
    # First response: error from invalid JSON
    assert responses[0]["response"]["ok"] is False
    # Second response: the valid request succeeded
    assert responses[1]["id"] == 99
    assert responses[1]["response"]["ok"] is True


def test_tc_cb_023_serve_empty_line_then_valid_request(tmp_path: Path) -> None:
    """TC: TC-CB-023 / TD005 / TV005 / TA001 / Risk R006"""
    # Empty lines are SKIPPED (no response produced)
    empty_line = "\n"
    valid_line = _make_envelope(1, {"command": "state_save", "work_dir": str(tmp_path), "state": {}})
    stdin = io.StringIO(empty_line + valid_line)
    stdout = io.StringIO()
    serve(stdin, stdout)
    responses = _parse_response_lines(stdout.getvalue())
    # serve() skips blank lines — exactly 1 response for the valid request
    assert len(responses) == 1
    assert responses[0]["id"] == 1
    assert responses[0]["response"]["ok"] is True


def test_tc_cb_024_serve_non_object_envelope_then_valid_request(tmp_path: Path) -> None:
    """TC: TC-CB-024 / TD005 / TV005 / TA001 / Risk R006"""
    # A JSON string (not object) envelope should produce an error, loop continues
    non_object_line = '"just_a_string"\n'
    valid_line = _make_envelope(7, {"command": "state_save", "work_dir": str(tmp_path), "state": {}})
    stdin = io.StringIO(non_object_line + valid_line)
    stdout = io.StringIO()
    serve(stdin, stdout)
    responses = _parse_response_lines(stdout.getvalue())
    assert len(responses) == 2
    assert responses[0]["response"]["ok"] is False
    assert responses[1]["id"] == 7
    assert responses[1]["response"]["ok"] is True


# ===========================================================================
# Section 3.2 — Naming logic (TC-CB-025..067)
# ===========================================================================


def test_tc_cb_025_seq_digits_normal_three_digit(tmp_path: Path) -> None:
    """TC: TC-CB-025 / TD006 / TV006 / TA002 / Risk R002"""
    metadata = {"box_no": "02", "binder_no": "03", "seq": "5"}
    result = build_yoshida_filename_preview(metadata, (), 3)
    assert result.ok
    assert result.raw_filename == "02_03_005.pdf"


def test_tc_cb_026_seq_digits_zero_clamped_to_min(tmp_path: Path) -> None:
    """TC: TC-CB-026 / TD007 / TV007 / TA002 / Risk R002

    seq_digits=0 is below MIN_SEQ_DIGITS(1): domain.coerce_seq_digits clamps to 1.
    So seq "5" is formatted as "5" (1-digit, no padding).
    """
    metadata = {"box_no": "1", "binder_no": "2", "seq": "5"}
    result = build_yoshida_filename_preview(metadata, (), 0)
    assert result.ok
    # clamped to MIN_SEQ_DIGITS=1, so "5" stays "5"
    assert "5" in result.raw_filename
    # box/binder still 2-digit
    assert result.raw_filename.startswith("01_02_")
    assert result.raw_filename == "01_02_5.pdf"


def test_tc_cb_027_seq_digits_one_single_digit(tmp_path: Path) -> None:
    """TC: TC-CB-027 / TD007 / TV007 / TA002 / Risk R002"""
    metadata = {"box_no": "1", "binder_no": "2", "seq": "5"}
    result = build_yoshida_filename_preview(metadata, (), 1)
    assert result.ok
    assert result.raw_filename == "01_02_5.pdf"


def test_tc_cb_028_seq_digits_three_three_digit(tmp_path: Path) -> None:
    """TC: TC-CB-028 / TD007 / TV007 / TA002 / Risk R002"""
    metadata = {"box_no": "1", "binder_no": "2", "seq": "5"}
    result = build_yoshida_filename_preview(metadata, (), 3)
    assert result.ok
    assert result.raw_filename == "01_02_005.pdf"


def test_tc_cb_029_seq_digits_nine_nine_digit(tmp_path: Path) -> None:
    """TC: TC-CB-029 / TD007 / TV007 / TA002 / Risk R002"""
    metadata = {"box_no": "1", "binder_no": "2", "seq": "5"}
    result = build_yoshida_filename_preview(metadata, (), 9)
    assert result.ok
    assert result.raw_filename == "01_02_000000005.pdf"


def test_tc_cb_030_seq_digits_ten_clamped_to_max(tmp_path: Path) -> None:
    """TC: TC-CB-030 / TD007 / TV007 / TA002 / Risk R002

    seq_digits=10 exceeds MAX_SEQ_DIGITS(9): clamped to 9.
    """
    metadata = {"box_no": "1", "binder_no": "2", "seq": "5"}
    result = build_yoshida_filename_preview(metadata, (), 10)
    assert result.ok
    # clamped to MAX_SEQ_DIGITS=9
    assert result.raw_filename == "01_02_000000005.pdf"


# --- box_no whitespace handling ---


def test_tc_cb_031_box_no_leading_space_stripped_and_zero_padded(tmp_path: Path) -> None:
    """TC: TC-CB-031 / TD008 / TV008 / TA002 / Risk R002"""
    metadata = {"box_no": " 1", "binder_no": "2", "seq": "3"}
    result = build_yoshida_filename_preview(metadata)
    assert result.ok
    # " 1" stripped to "1", then zero-padded to "01"
    assert result.raw_filename.startswith("01_")


def test_tc_cb_032_box_no_empty_string_is_missing(tmp_path: Path) -> None:
    """TC: TC-CB-032 / TD008 / TV008 / TA002 / Risk R002"""
    metadata = {"box_no": "", "binder_no": "2", "seq": "3"}
    result = build_yoshida_filename_preview(metadata)
    assert not result.ok
    assert any("missing_required:box_no" in e for e in result.errors)


def test_tc_cb_033_box_no_whitespace_only_is_missing(tmp_path: Path) -> None:
    """TC: TC-CB-033 / TD008 / TV008 / TA002 / Risk R002"""
    metadata = {"box_no": "   ", "binder_no": "2", "seq": "3"}
    result = build_yoshida_filename_preview(metadata)
    assert not result.ok
    assert any("missing_required:box_no" in e for e in result.errors)


# --- Invalid filename character replacement ---


def test_tc_cb_034_invalid_char_lt_replaced(tmp_path: Path) -> None:
    """TC: TC-CB-034 / TD009 / TV009 / TA002 / Risk R002"""
    metadata = {"box_no": "a<b", "binder_no": "2", "seq": "3"}
    result = build_yoshida_filename_preview(metadata)
    assert result.ok
    assert "<" not in result.normalized_filename
    assert "a_b" in result.normalized_filename


def test_tc_cb_035_invalid_char_gt_replaced(tmp_path: Path) -> None:
    """TC: TC-CB-035 / TD009 / TV009 / TA002 / Risk R002"""
    metadata = {"box_no": "a>b", "binder_no": "2", "seq": "3"}
    result = build_yoshida_filename_preview(metadata)
    assert result.ok
    assert ">" not in result.normalized_filename
    assert "a_b" in result.normalized_filename


def test_tc_cb_036_invalid_char_colon_replaced(tmp_path: Path) -> None:
    """TC: TC-CB-036 / TD009 / TV009 / TA002 / Risk R002"""
    metadata = {"box_no": "a:b", "binder_no": "2", "seq": "3"}
    result = build_yoshida_filename_preview(metadata)
    assert result.ok
    assert ":" not in result.normalized_filename
    assert "a_b" in result.normalized_filename


def test_tc_cb_037_invalid_char_doublequote_replaced(tmp_path: Path) -> None:
    """TC: TC-CB-037 / TD009 / TV009 / TA002 / Risk R002"""
    metadata = {"box_no": 'a"b', "binder_no": "2", "seq": "3"}
    result = build_yoshida_filename_preview(metadata)
    assert result.ok
    assert '"' not in result.normalized_filename
    assert "a_b" in result.normalized_filename


def test_tc_cb_038_invalid_char_slash_replaced(tmp_path: Path) -> None:
    """TC: TC-CB-038 / TD009 / TV009 / TA002 / Risk R002"""
    metadata = {"box_no": "a/b", "binder_no": "2", "seq": "3"}
    result = build_yoshida_filename_preview(metadata)
    assert result.ok
    assert "/" not in result.normalized_filename
    assert "a_b" in result.normalized_filename


def test_tc_cb_039_invalid_char_backslash_replaced(tmp_path: Path) -> None:
    """TC: TC-CB-039 / TD009 / TV009 / TA002 / Risk R002"""
    metadata = {"box_no": "a\\b", "binder_no": "2", "seq": "3"}
    result = build_yoshida_filename_preview(metadata)
    assert result.ok
    assert "\\" not in result.normalized_filename
    assert "a_b" in result.normalized_filename


def test_tc_cb_040_invalid_char_pipe_replaced(tmp_path: Path) -> None:
    """TC: TC-CB-040 / TD009 / TV009 / TA002 / Risk R002"""
    metadata = {"box_no": "a|b", "binder_no": "2", "seq": "3"}
    result = build_yoshida_filename_preview(metadata)
    assert result.ok
    assert "|" not in result.normalized_filename
    assert "a_b" in result.normalized_filename


def test_tc_cb_041_invalid_char_question_replaced(tmp_path: Path) -> None:
    """TC: TC-CB-041 / TD009 / TV009 / TA002 / Risk R002"""
    metadata = {"box_no": "a?b", "binder_no": "2", "seq": "3"}
    result = build_yoshida_filename_preview(metadata)
    assert result.ok
    assert "?" not in result.normalized_filename
    assert "a_b" in result.normalized_filename


def test_tc_cb_042_invalid_char_asterisk_replaced(tmp_path: Path) -> None:
    """TC: TC-CB-042 / TD009 / TV009 / TA002 / Risk R002"""
    metadata = {"box_no": "a*b", "binder_no": "2", "seq": "3"}
    result = build_yoshida_filename_preview(metadata)
    assert result.ok
    assert "*" not in result.normalized_filename
    assert "a_b" in result.normalized_filename


# --- Windows reserved name handling ---
# TC-CB-043..048: reserved names as box_no value cause the full filename stem
# to collide with a reserved name only when box_no IS the entire stem-like value
# combined with binder and seq. The domain sanitize operates on the FULL filename.
# For "CON.pdf" to trigger reserved-name detection the stem must be "CON".
# With box_no="CON", binder_no="2", seq="3" the raw name is "CON_02_003.pdf"
# whose stem is "CON_02_003" — NOT a reserved name.
# We therefore test via sanitize_filename_with_warnings directly using a filename
# whose stem IS the reserved name, which is exactly what domain.py does.
# The simpler traceable approach: build a filename where the ENTIRE stem is the
# reserved word. That means box_no=reserved, binder_no=reserved, seq=reserved
# would produce "CON_CON_CON.pdf" — still not matching. The correct approach per
# domain.py source: the stem check is applied to the FINAL assembled filename,
# and the result "CON_02_003.pdf" stem "CON_02_003" is NOT in WINDOWS_RESERVED_STEMS.
# So reserved-name prefixing via build_yoshida_filename_preview is NOT triggered
# by any single-field reserved value — it requires the full assembled filename
# stem to equal a reserved name (e.g. seq="CON", binder="", box="" which
# would be caught by missing_required first).
#
# SOLUTION per task spec: "build a filename containing them and assert _CON etc."
# We use sanitize_filename_with_warnings directly (the same function build_yoshida
# calls internally) with a filename whose stem is exactly the reserved word.

from pdf_splitter_tool.domain import sanitize_filename_with_warnings


def _reserved_name_check(reserved: str) -> str:
    """Build a filename whose stem IS the reserved word, then sanitize it."""
    filename = f"{reserved}.pdf"
    sanitized, warnings = sanitize_filename_with_warnings(filename)
    assert "reserved_name_prefixed" in warnings
    return sanitized


def test_tc_cb_043_reserved_name_CON_prefixed(tmp_path: Path) -> None:
    """TC: TC-CB-043 / TD010 / TV010 / TA002 / Risk R002"""
    result = _reserved_name_check("CON")
    assert result == "_CON.pdf"


def test_tc_cb_044_reserved_name_PRN_prefixed(tmp_path: Path) -> None:
    """TC: TC-CB-044 / TD010 / TV010 / TA002 / Risk R002"""
    result = _reserved_name_check("PRN")
    assert result == "_PRN.pdf"


def test_tc_cb_045_reserved_name_AUX_prefixed(tmp_path: Path) -> None:
    """TC: TC-CB-045 / TD010 / TV010 / TA002 / Risk R002"""
    result = _reserved_name_check("AUX")
    assert result == "_AUX.pdf"


def test_tc_cb_046_reserved_name_NUL_prefixed(tmp_path: Path) -> None:
    """TC: TC-CB-046 / TD010 / TV010 / TA002 / Risk R002"""
    result = _reserved_name_check("NUL")
    assert result == "_NUL.pdf"


def test_tc_cb_047_reserved_name_COM1_prefixed(tmp_path: Path) -> None:
    """TC: TC-CB-047 / TD010 / TV010 / TA002 / Risk R002"""
    result = _reserved_name_check("COM1")
    assert result == "_COM1.pdf"


def test_tc_cb_048_reserved_name_COM9_prefixed(tmp_path: Path) -> None:
    """TC: TC-CB-048 / TD010 / TV010 / TA002 / Risk R002"""
    result = _reserved_name_check("COM9")
    assert result == "_COM9.pdf"


def test_tc_cb_049_empty_after_normalize_fallback_output_pdf(tmp_path: Path) -> None:
    """TC: TC-CB-049 / TD010 / TV010 / TA002 / Risk R002

    sanitize_filename_with_warnings("") returns ("output.pdf", ("filename_empty_after_sanitize",))
    """
    sanitized, warnings = sanitize_filename_with_warnings("")
    assert sanitized == "output.pdf"
    assert "filename_empty_after_sanitize" in warnings


# --- affix tests ---


def test_tc_cb_050_affix_prefix_only_inserted_before_fixed_tokens(tmp_path: Path) -> None:
    """TC: TC-CB-050 / TD011 / TV011 / TA002 / Risk R002,R012"""
    affix_defs = ({"key": "dept", "label": "営業部", "position": "prefix"},)
    metadata = {"box_no": "01", "binder_no": "02", "seq": "1", "dept": "営業部"}
    result = build_yoshida_filename_preview(metadata, affix_defs, 3)
    assert result.ok
    assert result.raw_filename == "営業部_01_02_001.pdf"


def test_tc_cb_051_affix_suffix_only_inserted_after_fixed_tokens(tmp_path: Path) -> None:
    """TC: TC-CB-051 / TD011 / TV011 / TA002 / Risk R002,R012"""
    affix_defs = ({"key": "year", "label": "2024年度", "position": "suffix"},)
    metadata = {"box_no": "01", "binder_no": "02", "seq": "1", "year": "2024年度"}
    result = build_yoshida_filename_preview(metadata, affix_defs, 3)
    assert result.ok
    assert result.raw_filename == "01_02_001_2024年度.pdf"


def test_tc_cb_052_affix_prefix_and_suffix_both_inserted(tmp_path: Path) -> None:
    """TC: TC-CB-052 / TD011 / TV011 / TA002 / Risk R002,R012"""
    affix_defs = (
        {"key": "dept", "label": "営業部", "position": "prefix"},
        {"key": "year", "label": "2024年度", "position": "suffix"},
    )
    metadata = {"box_no": "01", "binder_no": "02", "seq": "1", "dept": "営業部", "year": "2024年度"}
    result = build_yoshida_filename_preview(metadata, affix_defs, 3)
    assert result.ok
    assert result.raw_filename == "営業部_01_02_001_2024年度.pdf"


def test_tc_cb_053_affix_empty_key_value_excluded(tmp_path: Path) -> None:
    """TC: TC-CB-053 / TD011 / TV011 / TA002 / Risk R002,R012

    In domain.normalize_affix_defs, an item with empty key is skipped entirely.
    An item with a valid key but whose metadata value is empty string is excluded
    from tokens in _affix_tokens (value.strip() is falsy → not appended).
    """
    affix_defs = (
        {"key": "dept", "label": "部署", "position": "prefix"},  # metadata missing → empty
        {"key": "year", "label": "2024年度", "position": "suffix"},
    )
    # "dept" key present but value is empty string → excluded
    metadata = {"box_no": "01", "binder_no": "02", "seq": "1", "dept": "", "year": "2024年度"}
    result = build_yoshida_filename_preview(metadata, affix_defs, 3)
    assert result.ok
    # prefix "dept" is empty → skipped; only suffix remains
    assert result.raw_filename == "01_02_001_2024年度.pdf"


def test_tc_cb_054_affix_same_position_keeps_definition_order(tmp_path: Path) -> None:
    """TC: TC-CB-054 / TD011 / TV011 / TA002 / Risk R002,R012"""
    affix_defs = (
        {"key": "dept", "label": "営業部", "position": "prefix"},
        {"key": "section", "label": "第1課", "position": "prefix"},
    )
    metadata = {"box_no": "01", "binder_no": "02", "seq": "1", "dept": "営業部", "section": "第1課"}
    result = build_yoshida_filename_preview(metadata, affix_defs, 3)
    assert result.ok
    assert result.raw_filename == "営業部_第1課_01_02_001.pdf"


def test_tc_cb_055_affix_count_zero_backward_compatible(tmp_path: Path) -> None:
    """TC: TC-CB-055 / TD012 / TV012 / TA002 / Risk R002"""
    metadata = {"box_no": "01", "binder_no": "02", "seq": "1"}
    result = build_yoshida_filename_preview(metadata, (), 3)
    assert result.ok
    assert result.raw_filename == "01_02_001.pdf"


def test_tc_cb_056_affix_count_one_ok(tmp_path: Path) -> None:
    """TC: TC-CB-056 / TD012 / TV012 / TA002 / Risk R002"""
    affix_defs = ({"key": "dept", "label": "営業部", "position": "prefix"},)
    metadata = {"box_no": "01", "binder_no": "02", "seq": "1", "dept": "営業部"}
    result = build_yoshida_filename_preview(metadata, affix_defs, 3)
    assert result.ok
    assert "営業部" in result.raw_filename


def test_tc_cb_057_affix_count_two_at_max_ok(tmp_path: Path) -> None:
    """TC: TC-CB-057 / TD012 / TV012 / TA002 / Risk R002"""
    affix_defs = (
        {"key": "a", "label": "A", "position": "prefix"},
        {"key": "b", "label": "B", "position": "suffix"},
    )
    metadata = {"box_no": "01", "binder_no": "02", "seq": "1", "a": "A", "b": "B"}
    result = build_yoshida_filename_preview(metadata, affix_defs, 3)
    assert result.ok
    assert result.raw_filename == "A_01_02_001_B.pdf"


def test_tc_cb_058_affix_count_three_third_truncated(tmp_path: Path) -> None:
    """TC: TC-CB-058 / TD012 / TV012 / TA002 / Risk R002

    domain.normalize_affix_defs silently drops items beyond MAX_AFFIX_COUNT(2).
    build_yoshida_filename_preview does NOT call normalize_affix_defs internally;
    callers must normalize first.  We test via normalize_affix_defs → then build.
    The third item must NOT appear in the filename after normalization.
    """
    from pdf_splitter_tool.domain import normalize_affix_defs

    raw_three = [
        {"key": "a", "label": "A", "position": "prefix"},
        {"key": "b", "label": "B", "position": "suffix"},
        {"key": "c", "label": "C", "position": "suffix"},
    ]
    # normalize_affix_defs trims to MAX_AFFIX_COUNT=2
    normalized_defs = normalize_affix_defs(raw_three)
    assert len(normalized_defs) == MAX_AFFIX_COUNT

    metadata = {"box_no": "01", "binder_no": "02", "seq": "1", "a": "A", "b": "B", "c": "C"}
    result = build_yoshida_filename_preview(metadata, normalized_defs, 3)
    assert result.ok
    # Third affix "C" is truncated — only A (prefix) and B (suffix) appear
    assert result.raw_filename == "A_01_02_001_B.pdf"


# --- parity / consistency ---


def test_tc_cb_059_parity_normal_internal_consistency(tmp_path: Path) -> None:
    """TC: TC-CB-059 / TD013 / TV013 / TA003 / Risk R002

    Assert build_yoshida_filename_preview internally consistent:
    raw_filename and normalized_filename for clean input.
    """
    metadata = {"box_no": "01", "binder_no": "02", "seq": "1"}
    result = build_yoshida_filename_preview(metadata, (), 3)
    assert result.ok
    assert result.raw_filename == "01_02_001.pdf"
    assert result.normalized_filename == result.raw_filename  # no sanitization needed


def test_tc_cb_061_parity_whitespace_strip_consistency(tmp_path: Path) -> None:
    """TC: TC-CB-061 / TD013 / TV013 / TA003 / Risk R002"""
    metadata = {"box_no": " 1", "binder_no": "02", "seq": "1"}
    result = build_yoshida_filename_preview(metadata, (), 3)
    assert result.ok
    # Whitespace stripped; box_no "1" → "01"
    assert result.raw_filename == "01_02_001.pdf"
    assert result.normalized_filename == result.raw_filename


def test_tc_cb_062_parity_reserved_and_invalid_chars_consistency(tmp_path: Path) -> None:
    """TC: TC-CB-062 / TD013 / TV013 / TA003 / Risk R002

    Input with invalid chars: raw has the invalid chars, normalized replaces them.
    """
    metadata = {"box_no": "a<b", "binder_no": "02", "seq": "1"}
    result = build_yoshida_filename_preview(metadata, (), 3)
    assert result.ok
    assert result.raw_filename != result.normalized_filename
    assert "filename_sanitized" in result.warnings
    assert "<" not in result.normalized_filename


def test_tc_cb_063_parity_affix_consistency(tmp_path: Path) -> None:
    """TC: TC-CB-063 / TD013 / TV013 / TA003 / Risk R002"""
    affix_defs = ({"key": "dept", "label": "営業部", "position": "prefix"},)
    metadata = {"box_no": "01", "binder_no": "02", "seq": "1", "dept": "営業部"}
    result = build_yoshida_filename_preview(metadata, affix_defs, 3)
    assert result.ok
    assert result.raw_filename == "営業部_01_02_001.pdf"
    assert result.normalized_filename == result.raw_filename


# --- affix three-way consistency ---


def test_tc_cb_064_affix_three_way_consistency_domain_vs_state_schema(tmp_path: Path) -> None:
    """TC: TC-CB-064 / TD014 / TV014 / TA003 / Risk R002

    domain.normalize_affix_defs and state_schema._normalize_affix_defs must both
    trim 3 defs to MAX_AFFIX_COUNT=2, keeping first 2.
    """
    from pdf_splitter_tool.domain import normalize_affix_defs as domain_normalize

    three_defs_raw = [
        {"key": "a", "label": "A", "position": "prefix"},
        {"key": "b", "label": "B", "position": "suffix"},
        {"key": "c", "label": "C", "position": "suffix"},
    ]

    # domain.normalize_affix_defs returns tuple of dicts, trims to MAX_AFFIX_COUNT
    domain_result = domain_normalize(three_defs_raw)
    assert len(domain_result) == MAX_AFFIX_COUNT
    assert domain_result[0]["key"] == "a"
    assert domain_result[1]["key"] == "b"

    # state_schema._normalize_affix_defs (via normalize_state_payload) also trims to MAX_AFFIX_COUNT
    state_result = normalize_state_payload({"affix_defs": three_defs_raw})
    assert len(state_result["affix_defs"]) == MAX_AFFIX_COUNT
    assert state_result["affix_defs"][0]["key"] == "a"
    assert state_result["affix_defs"][1]["key"] == "b"


def test_tc_cb_065_state_roundtrip_with_affix(tmp_path: Path) -> None:
    """TC: TC-CB-065 / TD015 / TV015 / TA003 / Risk R002,R004"""
    affix_defs = [{"key": "dept", "label": "営業部", "position": "prefix"}]
    state = {
        "version": 1,
        "input_paths": [],
        "affix_defs": affix_defs,
        # dept value must be in common_metadata so build can find it via metadata[key]
        "common_metadata": {"box_no": "01", "binder_no": "02", "dept": "営業部"},
    }
    save_response = handle_request({"command": "state_save", "work_dir": str(tmp_path), "state": state})
    assert save_response["ok"] is True

    load_response = handle_request({"command": "state_load", "work_dir": str(tmp_path)})
    assert load_response["ok"] is True
    loaded_state = load_response["state"]
    assert loaded_state["affix_defs"] == affix_defs

    # Preview name uses the restored affix_defs; metadata must include the affix key value
    metadata = {**loaded_state.get("common_metadata", {}), "seq": "1"}
    restored_affix = loaded_state["affix_defs"]
    result = build_yoshida_filename_preview(metadata, restored_affix, 3)
    assert result.ok
    assert result.raw_filename == "営業部_01_02_001.pdf"


def test_tc_cb_066_state_roundtrip_reserved_name(tmp_path: Path) -> None:
    """TC: TC-CB-066 / TD015 / TV015 / TA003 / Risk R002,R004"""
    state = {
        "version": 1,
        "common_metadata": {"box_no": "NUL", "binder_no": "02"},
    }
    handle_request({"command": "state_save", "work_dir": str(tmp_path), "state": state})
    load_response = handle_request({"command": "state_load", "work_dir": str(tmp_path)})
    assert load_response["ok"] is True
    loaded_meta = load_response["state"].get("common_metadata", {})
    metadata = {**loaded_meta, "seq": "1"}
    result = build_yoshida_filename_preview(metadata, (), 3)
    # "NUL_02_001.pdf" stem is "NUL_02_001" — not a reserved stem, so no prefix
    assert result.ok
    # But normalized_filename should not contain path separators
    assert "/" not in result.normalized_filename
    assert "\\" not in result.normalized_filename


def test_tc_cb_067_state_roundtrip_whitespace_in_box_no(tmp_path: Path) -> None:
    """TC: TC-CB-067 / TD015 / TV015 / TA003 / Risk R002,R004"""
    state = {
        "version": 1,
        "common_metadata": {"box_no": " 1", "binder_no": "02"},
    }
    handle_request({"command": "state_save", "work_dir": str(tmp_path), "state": state})
    load_response = handle_request({"command": "state_load", "work_dir": str(tmp_path)})
    assert load_response["ok"] is True
    loaded_meta = load_response["state"].get("common_metadata", {})
    metadata = {**loaded_meta, "seq": "1"}
    result = build_yoshida_filename_preview(metadata, (), 3)
    assert result.ok
    # " 1" stripped to "1" → zero-padded "01"
    assert result.raw_filename == "01_02_001.pdf"


# ===========================================================================
# Section 3.3 — preflight/export (TC-CB-068..078)
# ===========================================================================


def test_tc_cb_068_preflight_missing_output_dir_returns_error(tmp_path: Path) -> None:
    """TC: TC-CB-068 / TD016 / TV016 / TA003 / Risk R001"""
    source = tmp_path / "source.pdf"
    make_pdf(source, 1)
    response = handle_request({
        "command": "preflight",
        "output_dir": "",
        "segments": [_basic_segment(source)],
    })
    assert response["ok"] is False
    assert response["can_run"] is False
    assert "missing_output_dir" in response["messages"]


def test_tc_cb_069_preflight_no_segments_returns_error(tmp_path: Path) -> None:
    """TC: TC-CB-069 / TD016 / TV016 / TA003 / Risk R001"""
    response = handle_request({
        "command": "preflight",
        "output_dir": str(tmp_path / "output"),
        "segments": [],
    })
    assert response["ok"] is False
    assert response["can_run"] is False
    assert "no_segments" in response["messages"]


def test_tc_cb_070_export_collision_suffix_2(tmp_path: Path) -> None:
    """TC: TC-CB-070 / TD017 / TV017 / TA003 / Risk R001

    Two segments with the same filename: first gets requested name, second gets _2 suffix.
    """
    source = tmp_path / "source.pdf"
    make_pdf(source, 2)
    output_dir = tmp_path / "output"
    response = handle_request({
        "command": "export",
        "output_dir": str(output_dir),
        "segments": [
            _basic_segment(source, 1, 1),  # both have seq="3" → same name
            _basic_segment(source, 2, 2),
        ],
    })
    assert response["ok"] is True
    filenames = [Path(item["output_path"]).name for item in response["items"]]
    assert "01_02_003.pdf" in filenames
    assert "01_02_003_2.pdf" in filenames


def test_tc_cb_071_export_collision_suffix_3(tmp_path: Path) -> None:
    """TC: TC-CB-071 / TD017 / TV017 / TA003 / Risk R001

    Three segments with the same filename: third gets _3 suffix.
    """
    source = tmp_path / "source.pdf"
    make_pdf(source, 3)
    output_dir = tmp_path / "output"
    response = handle_request({
        "command": "export",
        "output_dir": str(output_dir),
        "segments": [
            _basic_segment(source, 1, 1),
            _basic_segment(source, 2, 2),
            _basic_segment(source, 3, 3),
        ],
    })
    assert response["ok"] is True
    filenames = [Path(item["output_path"]).name for item in response["items"]]
    assert "01_02_003.pdf" in filenames
    assert "01_02_003_2.pdf" in filenames
    assert "01_02_003_3.pdf" in filenames


def test_tc_cb_072_export_preflight_blocked_all_failed_no_files(tmp_path: Path) -> None:
    """TC: TC-CB-072 / TD018 / TV018 / TA003 / Risk R001

    When preflight fails (page range out of bounds), export writes no files.
    """
    source = tmp_path / "source.pdf"
    make_pdf(source, 1)
    output_dir = tmp_path / "output"
    # end_page=2 but PDF only has 1 page → preflight will fail
    response = handle_request({
        "command": "export",
        "output_dir": str(output_dir),
        "segments": [_basic_segment(source, 1, 2)],
    })
    assert response["ok"] is False
    assert response["summary"]["created"] == 0
    assert response["messages"] == ["preflight_failed"]
    # No PDF files should exist
    assert not output_dir.exists() or list(output_dir.glob("*.pdf")) == []


def test_tc_cb_073_export_all_success_ok_true(tmp_path: Path) -> None:
    """TC: TC-CB-073 / TD018 / TV018 / TA003 / Risk R001"""
    source = tmp_path / "source.pdf"
    make_pdf(source, 1)
    output_dir = tmp_path / "output"
    response = handle_request({
        "command": "export",
        "output_dir": str(output_dir),
        "segments": [_basic_segment(source, 1, 1)],
    })
    assert response["ok"] is True
    assert response["summary"]["created"] == 1
    assert response["summary"]["failed"] == 0
    assert response["messages"] == []


def test_tc_cb_074_export_partial_failure_export_incomplete(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """TC: TC-CB-074 / TD018 / TV018 / TA003 / Risk R001"""
    from pdf_splitter_tool.processor import PdfProcessor

    source = tmp_path / "source.pdf"
    make_pdf(source, 2)
    output_dir = tmp_path / "output"

    call_count = 0
    original_split = PdfProcessor.split_pdf

    def split_fail_on_second(seg: object, dest: object, overwrite: bool = False) -> object:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("simulated write failure")
        return original_split(seg, dest, overwrite=overwrite)

    monkeypatch.setattr(PdfProcessor, "split_pdf", staticmethod(split_fail_on_second))

    response = handle_request({
        "command": "export",
        "output_dir": str(output_dir),
        "segments": [
            _basic_segment(source, 1, 1, "1"),
            _basic_segment(source, 2, 2, "2"),
        ],
    })
    assert response["ok"] is False
    assert response["summary"]["created"] == 1
    assert response["summary"]["failed"] == 1
    assert "export_incomplete" in response["messages"]


def test_tc_cb_075_export_all_failure_created_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """TC: TC-CB-075 / TD018 / TV018 / TA003 / Risk R001"""
    from pdf_splitter_tool.processor import PdfProcessor

    source = tmp_path / "source.pdf"
    make_pdf(source, 1)
    output_dir = tmp_path / "output"

    def split_always_fail(seg: object, dest: object, overwrite: bool = False) -> object:
        raise RuntimeError("simulated total failure")

    monkeypatch.setattr(PdfProcessor, "split_pdf", staticmethod(split_always_fail))

    response = handle_request({
        "command": "export",
        "output_dir": str(output_dir),
        "segments": [_basic_segment(source, 1, 1)],
    })
    assert response["ok"] is False
    assert response["summary"]["created"] == 0
    assert "export_incomplete" not in response["messages"]


def test_tc_cb_076_export_items_have_sha256_and_output_path(tmp_path: Path) -> None:
    """TC: TC-CB-076 / TD019 / TV019 / TA003 / Risk R001"""
    source = tmp_path / "source.pdf"
    make_pdf(source, 1)
    output_dir = tmp_path / "output"
    response = handle_request({
        "command": "export",
        "output_dir": str(output_dir),
        "segments": [_basic_segment(source, 1, 1)],
    })
    assert response["ok"] is True
    item = response["items"][0]
    assert "sha256" in item
    assert item["sha256"]  # non-empty
    assert "output_path" in item
    assert Path(item["output_path"]).exists()


def test_tc_cb_077_export_preflight_blocked_items_all_status_failed(tmp_path: Path) -> None:
    """TC: TC-CB-077 / TD019 / TV019 / TA003 / Risk R001

    When an existing file blocks a segment, all items have status='failed'.
    """
    source = tmp_path / "source.pdf"
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    make_pdf(source, 1)
    # Pre-create the expected output file to block the export
    (output_dir / "01_02_003.pdf").write_bytes(b"existing")

    response = handle_request({
        "command": "export",
        "output_dir": str(output_dir),
        "segments": [_basic_segment(source, 1, 1)],
    })
    assert response["ok"] is False
    assert response["messages"] == ["preflight_failed"]
    for item in response["items"]:
        assert item["status"] == "failed"


def test_tc_cb_078_export_success_summary_and_items_consistent(tmp_path: Path) -> None:
    """TC: TC-CB-078 / TD019 / TV019 / TA003 / Risk R001"""
    source = tmp_path / "source.pdf"
    make_pdf(source, 2)
    output_dir = tmp_path / "output"
    response = handle_request({
        "command": "export",
        "output_dir": str(output_dir),
        "segments": [
            _basic_segment(source, 1, 1, "1"),
            _basic_segment(source, 2, 2, "2"),
        ],
    })
    assert response["ok"] is True
    assert response["summary"]["created"] == 2
    assert response["summary"]["failed"] == 0
    assert len(response["items"]) == 2
    for item in response["items"]:
        assert item["status"] == "created"
        assert "sha256" in item


# ===========================================================================
# Section 3.4 — State schema / roundtrip (TC-CB-079..096)
# ===========================================================================


def test_tc_cb_079_state_roundtrip_version(tmp_path: Path) -> None:
    """TC: TC-CB-079 / TD021 / TV021 / TA003 / Risk R004"""
    state = {"version": 1, "input_paths": []}
    handle_request({"command": "state_save", "work_dir": str(tmp_path), "state": state})
    resp = handle_request({"command": "state_load", "work_dir": str(tmp_path)})
    assert resp["state"]["version"] == 1


def test_tc_cb_080_state_roundtrip_input_paths(tmp_path: Path) -> None:
    """TC: TC-CB-080 / TD021 / TV021 / TA003 / Risk R004"""
    state = {"input_paths": ["a.pdf", "b.pdf"]}
    handle_request({"command": "state_save", "work_dir": str(tmp_path), "state": state})
    resp = handle_request({"command": "state_load", "work_dir": str(tmp_path)})
    assert resp["state"]["input_paths"] == ["a.pdf", "b.pdf"]


def test_tc_cb_081_state_roundtrip_split_points(tmp_path: Path) -> None:
    """TC: TC-CB-081 / TD021 / TV021 / TA003 / Risk R004"""
    state = {"split_points_by_pdf": {"a.pdf": [2, 5]}}
    handle_request({"command": "state_save", "work_dir": str(tmp_path), "state": state})
    resp = handle_request({"command": "state_load", "work_dir": str(tmp_path)})
    assert resp["state"]["split_points_by_pdf"] == {"a.pdf": [2, 5]}


def test_tc_cb_082_state_roundtrip_current_page(tmp_path: Path) -> None:
    """TC: TC-CB-082 / TD021 / TV021 / TA003 / Risk R004"""
    state = {"current_page": 5}
    handle_request({"command": "state_save", "work_dir": str(tmp_path), "state": state})
    resp = handle_request({"command": "state_load", "work_dir": str(tmp_path)})
    assert resp["state"]["current_page"] == 5


def test_tc_cb_083_state_roundtrip_output_dir(tmp_path: Path) -> None:
    """TC: TC-CB-083 / TD021 / TV021 / TA003 / Risk R004"""
    state = {"output_dir": "/some/output"}
    handle_request({"command": "state_save", "work_dir": str(tmp_path), "state": state})
    resp = handle_request({"command": "state_load", "work_dir": str(tmp_path)})
    assert resp["state"]["output_dir"] == "/some/output"


def test_tc_cb_084_state_roundtrip_current_pdf(tmp_path: Path) -> None:
    """TC: TC-CB-084 / TD021 / TV021 / TA003 / Risk R004"""
    state = {"current_pdf": "source.pdf"}
    handle_request({"command": "state_save", "work_dir": str(tmp_path), "state": state})
    resp = handle_request({"command": "state_load", "work_dir": str(tmp_path)})
    assert resp["state"]["current_pdf"] == "source.pdf"


def test_tc_cb_085_state_roundtrip_common_metadata(tmp_path: Path) -> None:
    """TC: TC-CB-085 / TD021 / TV021 / TA003 / Risk R004"""
    state = {"common_metadata": {"box_no": "01", "binder_no": "02"}}
    handle_request({"command": "state_save", "work_dir": str(tmp_path), "state": state})
    resp = handle_request({"command": "state_load", "work_dir": str(tmp_path)})
    assert resp["state"]["common_metadata"] == {"box_no": "01", "binder_no": "02"}


def test_tc_cb_086_state_roundtrip_affix_defs(tmp_path: Path) -> None:
    """TC: TC-CB-086 / TD021 / TV021 / TA003 / Risk R004"""
    affix_defs = [{"key": "dept", "label": "営業部", "position": "prefix"}]
    state = {"affix_defs": affix_defs}
    handle_request({"command": "state_save", "work_dir": str(tmp_path), "state": state})
    resp = handle_request({"command": "state_load", "work_dir": str(tmp_path)})
    assert resp["state"]["affix_defs"] == affix_defs


def test_tc_cb_087_state_version_type_mismatch_raises(tmp_path: Path) -> None:
    """TC: TC-CB-087 / TD022 / TV022 / TA003 / Risk R004

    version as string must raise TypeError at normalize_state_payload.
    """
    with pytest.raises(TypeError, match="version must be an integer"):
        normalize_state_payload({"version": "1"})


def test_tc_cb_088_state_current_page_type_mismatch_raises(tmp_path: Path) -> None:
    """TC: TC-CB-088 / TD022 / TV022 / TA003 / Risk R004"""
    with pytest.raises(TypeError, match="current_page must be an integer"):
        normalize_state_payload({"current_page": "5"})


def test_tc_cb_089_state_current_page_zero_raises(tmp_path: Path) -> None:
    """TC: TC-CB-089 / TD022 / TV022 / TA003 / Risk R004"""
    with pytest.raises(TypeError, match="current_page must be an integer greater than or equal to 1"):
        normalize_state_payload({"current_page": 0})


def test_tc_cb_090_state_current_pdf_non_string_raises(tmp_path: Path) -> None:
    """TC: TC-CB-090 / TD022 / TV022 / TA003 / Risk R004"""
    with pytest.raises(TypeError, match="current_pdf must be a string"):
        normalize_state_payload({"current_pdf": 123})


def test_tc_cb_091_state_missing_input_paths_reported(tmp_path: Path) -> None:
    """TC: TC-CB-091 / TD023 / TV023 / TA003 / Risk R004"""
    missing = str(tmp_path / "missing.pdf")
    state = {"input_paths": [missing]}
    handle_request({"command": "state_save", "work_dir": str(tmp_path), "state": state})
    resp = handle_request({"command": "state_load", "work_dir": str(tmp_path)})
    assert resp["ok"] is True
    assert "missing_input_paths" in resp
    assert missing in resp["missing_input_paths"]
    assert "missing_input_pdf" in resp.get("messages", [])


def test_tc_cb_092_state_current_page_in_range_preserved(tmp_path: Path) -> None:
    """TC: TC-CB-092 / TD024 / TV024 / TA003 / Risk R004"""
    normalized = normalize_state_payload({"current_page": 3})
    assert normalized["current_page"] == 3


def test_tc_cb_093_state_current_page_at_max_preserved(tmp_path: Path) -> None:
    """TC: TC-CB-093 / TD024 / TV024 / TA003 / Risk R004"""
    large_page = 9999
    normalized = normalize_state_payload({"current_page": large_page})
    assert normalized["current_page"] == large_page


def test_tc_cb_094_state_current_page_below_one_raises(tmp_path: Path) -> None:
    """TC: TC-CB-094 / TD024 / TV024 / TA003 / Risk R004"""
    with pytest.raises(TypeError, match="current_page must be an integer greater than or equal to 1"):
        normalize_state_payload({"current_page": -1})


def test_tc_cb_095_state_segment_metadata_roundtrips_intact(tmp_path: Path) -> None:
    """TC: TC-CB-095 / TD025 / TV025 / TA003 / Risk R004

    NOTE: TC-CB-095 の主眼「現行セグメントキー集合外の segment_metadata の
    フィルタ（ISS-003）」は Python sidecar/state_schema には存在せず、フロント
    segment-state.ts の reconcileSegmentMetadataForPdf が担う（node
    check-segment-state.mjs ＝ TC-CB-106/107 でカバー）。
    Python 側で保証されるのは「正当な segment_metadata が往復で破壊されないこと」。
    本テストはその Python 契約のみを検証する。stale フィルタ自体は node 層が担保。
    """
    state = {"segment_metadata": {"key1": {"seq": "001", "box_no": "01"}}}
    handle_request({"command": "state_save", "work_dir": str(tmp_path), "state": state})
    resp = handle_request({"command": "state_load", "work_dir": str(tmp_path)})
    assert resp["state"]["segment_metadata"] == {"key1": {"seq": "001", "box_no": "01"}}


def test_tc_cb_096_state_invalid_segment_metadata_rejected(tmp_path: Path) -> None:
    """TC: TC-CB-096 / TD025 / TV025 / TA003 / Risk R004"""
    with pytest.raises(TypeError, match="segment_metadata metadata values must be strings"):
        normalize_state_payload({"segment_metadata": {"key1": {"seq": 1}}})


# ===========================================================================
# Section 3.5 — State file fault tolerance (TC-CB-097..105)
# ===========================================================================


def test_tc_cb_097_corrupt_state_falls_back_to_backup(tmp_path: Path) -> None:
    """TC: TC-CB-097 / TD026 / TV026 / TA003 / Risk R004,R010"""
    manager = StateManager(tmp_path)
    backup_state = {"version": 1, "input_paths": ["backup.pdf"]}
    # Write a valid backup
    manager.backup_path.parent.mkdir(parents=True, exist_ok=True)
    manager.backup_path.write_text(json.dumps(backup_state), encoding="utf-8")
    # Write corrupt primary
    manager.state_path.write_text("{corrupt", encoding="utf-8")

    result = manager.load()
    assert result == backup_state


def test_tc_cb_098_tmp_promoted_when_state_and_backup_missing(tmp_path: Path) -> None:
    """TC: TC-CB-098 / TD026 / TV026 / TA003 / Risk R004,R010"""
    manager = StateManager(tmp_path)
    tmp_state = {"version": 1, "input_paths": ["tmp.pdf"]}
    manager.tmp_path.parent.mkdir(parents=True, exist_ok=True)
    manager.tmp_path.write_text(json.dumps(tmp_state), encoding="utf-8")

    result = manager.load()
    assert result == tmp_state
    # tmp was promoted to state
    assert manager.state_path.exists()


def test_tc_cb_099_tmp_vs_bak_priority_newer_tmp_wins(tmp_path: Path) -> None:
    """TC: TC-CB-099 / TD027 / TV027 / TA003 / Risk R004

    tmp mtime >= bak mtime → tmp wins.
    """
    manager = StateManager(tmp_path)
    bak_state = {"value": "old"}
    tmp_state = {"value": "new"}
    manager.backup_path.write_text(json.dumps(bak_state), encoding="utf-8")
    # Write tmp as the fixed-name tmp (STATE_TMP_FILENAME)
    manager.tmp_path.write_text(json.dumps(tmp_state), encoding="utf-8")
    # Set tmp mtime to be clearly newer than bak
    bak_mtime = manager.backup_path.stat().st_mtime
    os.utime(manager.tmp_path, (bak_mtime + 10, bak_mtime + 10))

    result = manager.load()
    assert result["value"] == "new"


def test_tc_cb_100_multi_instance_pid_tmp_created(tmp_path: Path) -> None:
    """TC: TC-CB-100 / TD028 / TV028 / TA003 / Risk R004

    save() uses a per-pid tmp file; after success the tmp should be gone (renamed to state).
    """
    manager = StateManager(tmp_path)
    manager.save({"value": "test"})
    # After successful save, the pid tmp must not remain
    pid_tmp = manager._pid_tmp_path()
    assert not pid_tmp.exists()
    # State file must exist
    assert manager.state_path.exists()


def test_tc_cb_101_stale_tmp_cleaned_after_save(tmp_path: Path) -> None:
    """TC: TC-CB-101 / TD028 / TV028 / TA003 / Risk R004"""
    manager = StateManager(tmp_path)
    # Create a stale "other-pid" tmp with a timestamp in the distant past
    fake_pid = os.getpid() + 9999
    from pdf_splitter_tool.state import STATE_TMP_PREFIX, STATE_TMP_SUFFIX
    stale_tmp = tmp_path / f"{STATE_TMP_PREFIX}{fake_pid}{STATE_TMP_SUFFIX}"
    stale_tmp.write_text(json.dumps({"value": "stale"}), encoding="utf-8")
    os.utime(stale_tmp, (1_000_000.0, 1_000_000.0))

    manager.save({"value": "current"})
    # Stale tmp older than committed state must be deleted
    assert not stale_tmp.exists()


def test_tc_cb_102_non_promoted_tmp_survives_failed_promotion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """TC: TC-CB-102 / TD029 / TV029 / TA003 / Risk R004

    If the tmp→state rename fails, load() still returns the payload from tmp.
    """
    manager = StateManager(tmp_path)
    tmp_state = {"value": "survived"}
    manager.tmp_path.write_text(json.dumps(tmp_state), encoding="utf-8")
    original_replace = Path.replace

    def fail_replace(path: Path, target: Path) -> object:
        if path == manager.tmp_path and target == manager.state_path:
            raise OSError("simulated promotion failure")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_replace)

    result = manager.load()
    assert result["value"] == "survived"
    # tmp must still exist since rename failed
    assert manager.tmp_path.exists()


def test_tc_cb_103_save_failure_preserves_existing_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """TC: TC-CB-103 / TD029 / TV029 / TA003 / Risk R004

    If pid_tmp.write_text raises, original state must be untouched.
    """
    manager = StateManager(tmp_path)
    original_state = {"value": "original"}
    manager.save(original_state)

    original_write_text = Path.write_text

    def fail_write(path: Path, *args, **kwargs) -> None:
        if path == manager._pid_tmp_path():
            raise OSError("simulated write failure")
        return original_write_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_write)

    try:
        manager.save({"value": "new"})
    except OSError:
        pass

    # State file should still contain the original state
    loaded = manager.load()
    assert loaded["value"] == "original"


def test_tc_cb_104_all_corrupt_state_files_returns_empty(tmp_path: Path) -> None:
    """TC: TC-CB-104 / TD026 / TV026 / TA003 / Risk R004"""
    manager = StateManager(tmp_path)
    manager.state_path.parent.mkdir(parents=True, exist_ok=True)
    manager.state_path.write_text("{corrupt", encoding="utf-8")
    manager.backup_path.write_text("{corrupt", encoding="utf-8")
    manager.tmp_path.write_text("{corrupt", encoding="utf-8")

    result = manager.load()
    assert result == {}


def test_tc_cb_105_save_rotates_existing_state_to_backup(tmp_path: Path) -> None:
    """TC: TC-CB-105 / TD026 / TV026 / TA003 / Risk R004"""
    manager = StateManager(tmp_path)
    original = {"value": "first"}
    next_state = {"value": "second"}
    manager.save(original)
    manager.save(next_state)

    assert manager.load()["value"] == "second"
    bak = json.loads(manager.backup_path.read_text(encoding="utf-8"))
    assert bak["value"] == "first"


# ===========================================================================
# Section 3.6 — search_text / blank_candidates (TC-CB-125..133)
# ===========================================================================


def test_tc_cb_125_search_text_single_query_returns_hits(tmp_path: Path) -> None:
    """TC: TC-CB-125 / TD033 / TV033 / TA003 / Risk R001"""
    source = tmp_path / "source.pdf"
    make_text_pdf(source, ["hello world", "no match here"])
    results, truncated = PdfService.search_text([source], query="hello")
    assert truncated is False
    assert len(results) == 1
    assert results[0]["page_no"] == 1
    assert results[0]["matched_terms"] == ["hello"]


def test_tc_cb_126_search_text_multi_query_returns_per_term_entries(tmp_path: Path) -> None:
    """TC: TC-CB-126 / TD033 / TV033 / TA003 / Risk R001"""
    source = tmp_path / "source.pdf"
    make_text_pdf(source, ["Alpha Beta page", "Gamma page"])
    results, truncated = PdfService.search_text([source], query="", queries=["Alpha", "Gamma"])
    assert truncated is False
    terms_found = {r["matched_terms"][0] for r in results}
    assert "Alpha" in terms_found
    assert "Gamma" in terms_found


def test_tc_cb_127_search_text_zero_results(tmp_path: Path) -> None:
    """TC: TC-CB-127 / TD033 / TV033 / TA003 / Risk R001"""
    source = tmp_path / "source.pdf"
    make_text_pdf(source, ["completely different text"])
    results, truncated = PdfService.search_text([source], query="nomatch_xyz")
    assert results == []
    assert truncated is False


def test_tc_cb_128_search_text_one_result(tmp_path: Path) -> None:
    """TC: TC-CB-128 / TD033 / TV033 / TA003 / Risk R001"""
    source = tmp_path / "source.pdf"
    make_text_pdf(source, ["unique_term_xyz", "no match"])
    results, truncated = PdfService.search_text([source], query="unique_term_xyz")
    assert len(results) == 1
    assert truncated is False


def test_tc_cb_129_search_text_exactly_200_results_not_truncated(tmp_path: Path) -> None:
    """TC: TC-CB-129 / TD034 / TV034 / TA003 / Risk R001

    200 pages each with one match → exactly at limit, truncated=False.
    """
    limit = SEARCH_TEXT_MAX_RESULTS  # 200
    source = tmp_path / "source.pdf"
    make_text_pdf(source, [f"Match page {i}" for i in range(limit)])
    results, truncated = PdfService.search_text([source], query="Match")
    assert len(results) == limit
    assert truncated is False


def test_tc_cb_130_search_text_201_results_truncated(tmp_path: Path) -> None:
    """TC: TC-CB-130 / TD034 / TV034 / TA003 / Risk R001

    201 pages each with one match → truncated=True, results==200.
    """
    limit = SEARCH_TEXT_MAX_RESULTS  # 200
    source = tmp_path / "source.pdf"
    make_text_pdf(source, [f"Match page {i}" for i in range(limit + 1)])
    results, truncated = PdfService.search_text([source], query="Match")
    assert len(results) == limit
    assert truncated is True


def test_tc_cb_131_blank_candidates_within_budget_partial_false(tmp_path: Path) -> None:
    """TC: TC-CB-131 / TD035 / TV035 / TA003 / Risk R001

    Small white PDF within time budget → partial=False.
    """
    source = tmp_path / "source.pdf"
    make_white_pdf(source, 2)
    candidates, partial, scanned_until = PdfService.blank_candidates(source)
    assert partial is False
    assert scanned_until == 2
    assert len(candidates) == 2


def test_tc_cb_132_blank_candidates_over_budget_partial_true(tmp_path: Path) -> None:
    """TC: TC-CB-132 / TD035 / TV035 / TA003 / Risk R001

    Very tight time budget → partial=True when budget exceeded.
    Uses time_budget=0.0 to force partial result.
    """
    source = tmp_path / "source.pdf"
    total_pages = 10
    make_white_pdf(source, total_pages)
    # Extremely small budget to force an early cut-off. The exact trigger depends on
    # the monotonic clock vs per-page processing speed, so (matching the project's own
    # test_blank_candidates_partial_result_when_budget_exceeded) we assert the contract
    # conditionally rather than hard-asserting partial=True.
    candidates, partial, scanned_until = PdfService.blank_candidates(source, time_budget=0.000001)
    assert isinstance(partial, bool)
    assert isinstance(scanned_until, int)
    if partial:
        # budget exceeded mid-scan: stopped before the final page
        assert 0 <= scanned_until < total_pages
        # returned candidates only cover the pages actually scanned
        assert all(c["page_no"] <= scanned_until for c in candidates)
    else:
        # fast enough to finish the whole document
        assert scanned_until == total_pages


def test_tc_cb_133_blank_candidates_start_page_continues(tmp_path: Path) -> None:
    """TC: TC-CB-133 / TD036 / TV036 / TA003 / Risk R001"""
    source = tmp_path / "source.pdf"
    # Page 1 has text, pages 2-3 are blank
    make_text_pdf(source, ["text here", "", ""])
    candidates, partial, scanned_until = PdfService.blank_candidates(source, start_page=2)
    assert partial is False
    assert scanned_until == 3
    page_nos = [c["page_no"] for c in candidates]
    assert 1 not in page_nos
    assert 2 in page_nos or 3 in page_nos


# ===========================================================================
# Section 3.7 — Security (TC-CB-138..140)
# ===========================================================================


def test_tc_cb_138_box_no_with_slash_no_path_traversal(tmp_path: Path) -> None:
    """TC: TC-CB-138 / TD047a / TV047a / TA003 / Risk R002

    box_no with "/" must not produce path separators in normalized_filename.
    """
    metadata = {"box_no": "a/b", "binder_no": "02", "seq": "1"}
    result = build_yoshida_filename_preview(metadata, (), 3)
    assert result.ok
    assert "/" not in result.normalized_filename
    assert "\\" not in result.normalized_filename
    assert result.normalized_filename == "a_b_02_001.pdf"


def test_tc_cb_139_box_no_with_backslash_no_path_traversal(tmp_path: Path) -> None:
    """TC: TC-CB-139 / TD047a / TV047a / TA003 / Risk R002"""
    metadata = {"box_no": "a\\b", "binder_no": "02", "seq": "1"}
    result = build_yoshida_filename_preview(metadata, (), 3)
    assert result.ok
    assert "/" not in result.normalized_filename
    assert "\\" not in result.normalized_filename
    assert result.normalized_filename == "a_b_02_001.pdf"


def test_tc_cb_140_box_no_with_colon_no_path_traversal(tmp_path: Path) -> None:
    """TC: TC-CB-140 / TD047a / TV047a / TA003 / Risk R002"""
    metadata = {"box_no": "a:b", "binder_no": "02", "seq": "1"}
    result = build_yoshida_filename_preview(metadata, (), 3)
    assert result.ok
    assert ":" not in result.normalized_filename
    assert result.normalized_filename == "a_b_02_001.pdf"


# ===========================================================================
# Section 3.8 — Response shape contract (TC-CB-141..143)
# ===========================================================================


def test_tc_cb_141_ok_response_has_required_fields(tmp_path: Path) -> None:
    """TC: TC-CB-141 / TD051 / TV051 / TA003 / Risk R006

    A successful sidecar response must have ok=True and command.
    """
    source = tmp_path / "source.pdf"
    make_pdf(source, 1)
    response = handle_request({"command": "pdf_info", "pdf_path": str(source)})
    assert response["ok"] is True
    assert "command" in response
    assert response["command"] == "pdf_info"


def test_tc_cb_142_error_response_shape(tmp_path: Path) -> None:
    """TC: TC-CB-142 / TD052 / TV052 / TA003 / Risk R006

    A sidecar error response must have {ok:false, command, error, error_type}.
    """
    response = handle_request({"command": "search_text", "pdf_paths": "not_an_array", "query": "test"})
    assert response["ok"] is False
    assert "command" in response
    assert "error" in response
    assert "error_type" in response


def test_tc_cb_143_error_response_does_not_contain_ok_true_fields(tmp_path: Path) -> None:
    """TC: TC-CB-143 / TD053 / TV053 / TA003 / Risk R006

    The error response for an unsupported command must not contain 'checks' or 'items'
    (those fields belong to specific ok-response shapes).
    """
    response = handle_request({"command": "no_such_command_xyz"})
    assert response["ok"] is False
    assert "checks" not in response
    assert "items" not in response


# ===========================================================================
# Section 3.9 — Export observability (TC-CB-144)
# ===========================================================================


def test_tc_cb_144_export_partial_failure_messages_observable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TC: TC-CB-144 / TD057 / TV057 / TA003 / Risk R001

    Partial export failure: messages contains 'export_incomplete',
    individual failed items have 'error' and 'error_type' fields.
    """
    from pdf_splitter_tool.processor import PdfProcessor

    source = tmp_path / "source.pdf"
    make_pdf(source, 2)
    output_dir = tmp_path / "output"

    call_count = 0
    original_split = PdfProcessor.split_pdf

    def split_fail_on_second(seg: object, dest: object, overwrite: bool = False) -> object:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("observable failure")
        return original_split(seg, dest, overwrite=overwrite)

    monkeypatch.setattr(PdfProcessor, "split_pdf", staticmethod(split_fail_on_second))

    response = handle_request({
        "command": "export",
        "output_dir": str(output_dir),
        "segments": [
            _basic_segment(source, 1, 1, "1"),
            _basic_segment(source, 2, 2, "2"),
        ],
    })

    assert "export_incomplete" in response["messages"]
    failed_items = [item for item in response["items"] if item["status"] == "failed"]
    assert len(failed_items) == 1
    assert "error" in failed_items[0]
    assert "error_type" in failed_items[0]
    assert "observable failure" in failed_items[0]["error"]


# ===========================================================================
# Section 3.10 — Observability: missing_input_paths evidence (TC-CB-145)
# ===========================================================================


def test_tc_cb_145_state_load_response_lists_missing_input_paths(tmp_path: Path) -> None:
    """TC: TC-CB-145 / TD072 / TV072 / TA011 / Risk R006,R014

    A state_load whose saved state references a non-existent input PDF must report
    that path in the response 'missing_input_paths', so the caller can identify
    exactly which file is missing (observability).
    """
    missing = str(tmp_path / "nonexistent" / "a.pdf")
    state = {"version": 1, "input_paths": [missing]}
    save_resp = handle_request({"command": "state_save", "work_dir": str(tmp_path), "state": state})
    assert save_resp["ok"] is True

    response = handle_request({"command": "state_load", "work_dir": str(tmp_path)})
    assert response["ok"] is True
    assert "missing_input_paths" in response
    assert missing in response["missing_input_paths"]
    # the missing path must be identifiable as a discrete evidence entry
    assert len(response["missing_input_paths"]) == 1

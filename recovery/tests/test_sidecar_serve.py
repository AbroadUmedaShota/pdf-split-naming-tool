"""Tests for sidecar.serve() — the resident JSON Lines serve loop.

Unit tests use io.StringIO so no subprocess or PyMuPDF dependency is needed.
Integration tests spawn a real subprocess to verify protocol compliance and
clean exit-on-EOF behaviour.
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
import textwrap
import time

import pytest

from pdf_splitter_tool.sidecar import serve


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_envelope(request_id: int, request: dict) -> str:
    return json.dumps({"id": request_id, "request": request}, separators=(",", ":")) + "\n"


def _parse_response_lines(output: str) -> list[dict]:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


# ---------------------------------------------------------------------------
# Unit tests (StringIO — no subprocess, no PyMuPDF)
# ---------------------------------------------------------------------------


class TestServeUnit:
    def test_single_valid_request_returns_matching_id(self) -> None:
        """A well-formed envelope for an unknown command returns ok:false with the same id."""
        request = _make_envelope(1, {"command": "unknown_cmd_for_test"})
        stdin = io.StringIO(request)
        stdout = io.StringIO()

        serve(stdin, stdout)

        responses = _parse_response_lines(stdout.getvalue())
        assert len(responses) == 1
        env = responses[0]
        assert env["id"] == 1
        assert env["response"]["ok"] is False

    def test_id_is_echoed_back_for_each_request(self) -> None:
        """Each response must carry the same id as its request."""
        lines = "".join(
            _make_envelope(rid, {"command": "unknown_cmd"}) for rid in (10, 20, 30)
        )
        stdin = io.StringIO(lines)
        stdout = io.StringIO()

        serve(stdin, stdout)

        responses = _parse_response_lines(stdout.getvalue())
        assert [r["id"] for r in responses] == [10, 20, 30]

    def test_multiple_requests_produce_multiple_responses(self) -> None:
        """Three requests must yield exactly three response lines."""
        lines = "".join(_make_envelope(i, {"command": "unknown_cmd"}) for i in range(3))
        stdin = io.StringIO(lines)
        stdout = io.StringIO()

        serve(stdin, stdout)

        responses = _parse_response_lines(stdout.getvalue())
        assert len(responses) == 3

    def test_malformed_json_returns_id_null_error_and_loop_continues(self) -> None:
        """A non-parseable line must produce id:null error; subsequent valid request is processed."""
        bad_line = "this is not json\n"
        good_line = _make_envelope(99, {"command": "unknown_cmd"})
        stdin = io.StringIO(bad_line + good_line)
        stdout = io.StringIO()

        serve(stdin, stdout)

        responses = _parse_response_lines(stdout.getvalue())
        assert len(responses) == 2

        bad_resp = responses[0]
        assert bad_resp["id"] is None
        assert bad_resp["response"]["ok"] is False

        good_resp = responses[1]
        assert good_resp["id"] == 99

    def test_envelope_missing_request_key_returns_error_with_envelope_id(self) -> None:
        """Envelope without 'request' key: id is preserved because JSON parsed OK.

        id:null is reserved for lines that cannot be parsed as JSON at all.
        When the envelope is valid JSON but the 'request' key is absent, the id
        from the envelope (5) must appear in the response.
        """
        envelope_no_request = json.dumps({"id": 5}) + "\n"
        good_line = _make_envelope(6, {"command": "unknown_cmd"})
        stdin = io.StringIO(envelope_no_request + good_line)
        stdout = io.StringIO()

        serve(stdin, stdout)

        responses = _parse_response_lines(stdout.getvalue())
        assert len(responses) == 2
        assert responses[0]["id"] == 5
        assert responses[0]["response"]["ok"] is False
        assert responses[1]["id"] == 6

    def test_empty_lines_are_skipped(self) -> None:
        """Blank lines between messages must not produce extra responses."""
        content = (
            "\n"
            + _make_envelope(1, {"command": "unknown_cmd"})
            + "\n\n"
            + _make_envelope(2, {"command": "unknown_cmd"})
            + "\n"
        )
        stdin = io.StringIO(content)
        stdout = io.StringIO()

        serve(stdin, stdout)

        responses = _parse_response_lines(stdout.getvalue())
        assert len(responses) == 2
        assert [r["id"] for r in responses] == [1, 2]

    def test_eof_terminates_normally_with_no_exception(self) -> None:
        """serve() must return normally when stdin is exhausted — no sys.exit or exception."""
        stdin = io.StringIO("")
        stdout = io.StringIO()
        # Should not raise
        serve(stdin, stdout)
        assert stdout.getvalue() == ""

    def test_each_response_is_compact_json_single_line(self) -> None:
        """Every response line must be valid JSON with no embedded newlines."""
        lines = _make_envelope(1, {"command": "unknown_cmd"})
        stdin = io.StringIO(lines)
        stdout = io.StringIO()

        serve(stdin, stdout)

        raw_lines = [l for l in stdout.getvalue().split("\n") if l.strip()]
        assert len(raw_lines) == 1
        parsed = json.loads(raw_lines[0])
        assert isinstance(parsed, dict)

    def test_multiple_malformed_lines_all_return_id_null(self) -> None:
        """Multiple bad lines each produce id:null; loop does not die after the first bad one."""
        bad_lines = "not json\n{broken\n"
        good_line = _make_envelope(7, {"command": "unknown_cmd"})
        stdin = io.StringIO(bad_lines + good_line)
        stdout = io.StringIO()

        serve(stdin, stdout)

        responses = _parse_response_lines(stdout.getvalue())
        assert len(responses) == 3
        assert responses[0]["id"] is None
        assert responses[1]["id"] is None
        assert responses[2]["id"] == 7

    def test_state_save_and_state_load_via_serve(self, tmp_path) -> None:
        """state_save + state_load round-trip through serve() with StringIO."""
        save_envelope = _make_envelope(
            1,
            {
                "command": "state_save",
                "work_dir": str(tmp_path),
                "state": {"hello": "world"},
            },
        )
        load_envelope = _make_envelope(
            2,
            {"command": "state_load", "work_dir": str(tmp_path)},
        )
        stdin = io.StringIO(save_envelope + load_envelope)
        stdout = io.StringIO()

        serve(stdin, stdout)

        responses = _parse_response_lines(stdout.getvalue())
        assert len(responses) == 2

        save_resp = responses[0]
        assert save_resp["id"] == 1
        assert save_resp["response"]["ok"] is True

        load_resp = responses[1]
        assert load_resp["id"] == 2
        assert load_resp["response"]["ok"] is True
        assert load_resp["response"]["state"]["hello"] == "world"

    def test_state_load_unc_work_dir_returns_error_response(self) -> None:
        """state_load with a UNC work_dir must return ok:false, not crash the loop."""
        unc_line = _make_envelope(
            1,
            {"command": "state_load", "work_dir": "\\\\server\\share\\work"},
        )
        good_line = _make_envelope(2, {"command": "unknown_cmd"})
        stdin = io.StringIO(unc_line + good_line)
        stdout = io.StringIO()

        serve(stdin, stdout)

        responses = _parse_response_lines(stdout.getvalue())
        assert len(responses) == 2
        assert responses[0]["id"] == 1
        assert responses[0]["response"]["ok"] is False
        # Loop survived: second request was also processed.
        assert responses[1]["id"] == 2


# ---------------------------------------------------------------------------
# Integration tests (real subprocess)
# ---------------------------------------------------------------------------


class TestServeSubprocess:
    """Spawn the real module with --sidecar-serve and verify protocol behaviour.

    Commands that do NOT require PyMuPDF (state_save / state_load / unknown
    command) are used to keep the test independent of the PDF fixtures.
    """

    def _spawn_serve(self) -> subprocess.Popen:
        return subprocess.Popen(
            [sys.executable, "-m", "pdf_splitter_tool", "--sidecar-serve"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )

    def _send_and_read(self, proc: subprocess.Popen, payload: str) -> dict:
        assert proc.stdin is not None
        assert proc.stdout is not None
        proc.stdin.write(payload)
        proc.stdin.flush()
        line = proc.stdout.readline()
        return json.loads(line)

    def test_single_request_returns_response_with_matching_id(self, tmp_path) -> None:
        proc = self._spawn_serve()
        try:
            envelope = _make_envelope(
                42,
                {"command": "state_save", "work_dir": str(tmp_path), "state": {}},
            )
            resp = self._send_and_read(proc, envelope)
            assert resp["id"] == 42
            assert resp["response"]["ok"] is True
        finally:
            proc.stdin.close()  # type: ignore[union-attr]
            proc.wait(timeout=5)

    def test_multiple_requests_processed_sequentially(self, tmp_path) -> None:
        proc = self._spawn_serve()
        try:
            ids = [1, 2, 3]
            payload = "".join(
                _make_envelope(
                    rid,
                    {"command": "state_save", "work_dir": str(tmp_path), "state": {"n": rid}},
                )
                for rid in ids
            )
            assert proc.stdin is not None
            assert proc.stdout is not None
            proc.stdin.write(payload)
            proc.stdin.flush()

            received_ids = []
            for _ in ids:
                line = proc.stdout.readline()
                env = json.loads(line)
                received_ids.append(env["id"])
                assert env["response"]["ok"] is True
            assert received_ids == ids
        finally:
            proc.stdin.close()  # type: ignore[union-attr]
            proc.wait(timeout=5)

    def test_bad_line_produces_id_null_and_loop_continues(self, tmp_path) -> None:
        proc = self._spawn_serve()
        try:
            assert proc.stdin is not None
            assert proc.stdout is not None

            # Send bad line
            proc.stdin.write("not valid json\n")
            proc.stdin.flush()
            bad_resp = json.loads(proc.stdout.readline())
            assert bad_resp["id"] is None
            assert bad_resp["response"]["ok"] is False

            # Send valid follow-up — loop must still be alive
            proc.stdin.write(
                _make_envelope(
                    55,
                    {"command": "state_save", "work_dir": str(tmp_path), "state": {}},
                )
            )
            proc.stdin.flush()
            good_resp = json.loads(proc.stdout.readline())
            assert good_resp["id"] == 55
            assert good_resp["response"]["ok"] is True
        finally:
            proc.stdin.close()  # type: ignore[union-attr]
            proc.wait(timeout=5)

    def test_stdin_close_causes_clean_exit_zero(self, tmp_path) -> None:
        proc = self._spawn_serve()
        # Send one request then immediately close stdin.
        assert proc.stdin is not None
        proc.stdin.write(
            _make_envelope(
                1,
                {"command": "state_save", "work_dir": str(tmp_path), "state": {}},
            )
        )
        proc.stdin.close()
        exit_code = proc.wait(timeout=10)
        assert exit_code == 0, f"Expected exit 0 on EOF, got {exit_code}"

    def test_empty_stdin_exits_zero(self) -> None:
        proc = self._spawn_serve()
        assert proc.stdin is not None
        proc.stdin.close()
        exit_code = proc.wait(timeout=10)
        assert exit_code == 0

    def test_unknown_command_returns_ok_false_not_crash(self, tmp_path) -> None:
        proc = self._spawn_serve()
        try:
            resp = self._send_and_read(proc, _make_envelope(9, {"command": "no_such_cmd"}))
            assert resp["id"] == 9
            assert resp["response"]["ok"] is False
        finally:
            proc.stdin.close()  # type: ignore[union-attr]
            proc.wait(timeout=5)

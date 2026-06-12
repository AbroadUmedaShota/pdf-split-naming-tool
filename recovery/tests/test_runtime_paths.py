from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from pdf_splitter_tool.runtime import default_work_dir, work_dir_from_request
from pdf_splitter_tool.state import STATE_FILENAME, STATE_TMP_PREFIX, STATE_TMP_SUFFIX, StateManager


def test_default_work_dir_uses_explicit_override(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PDF_ORGANIZER_WORK_DIR", str(tmp_path / "work"))

    assert default_work_dir() == tmp_path / "work"


def test_default_work_dir_uses_appdata_on_windows_style_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("PDF_ORGANIZER_WORK_DIR", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))

    assert default_work_dir() == tmp_path / "AppData" / "Roaming" / "PDF整理ツール"


def test_state_manager_writes_state_and_backup(tmp_path: Path) -> None:
    manager = StateManager(tmp_path)

    manager.save({"version": 1, "value": "first"})
    manager.save({"version": 1, "value": "second"})

    assert manager.load()["value"] == "second"
    assert manager.backup_path.exists()


def test_state_manager_falls_back_to_backup_when_state_is_broken(tmp_path: Path) -> None:
    manager = StateManager(tmp_path)

    manager.save({"version": 2, "value": "backup"})
    manager.save({"version": 2, "value": "current"})
    manager.state_path.write_text("{broken", encoding="utf-8")

    assert manager.load()["value"] == "backup"
    assert manager.state_path.exists()
    assert manager.backup_path.exists()


# ISS-011: crash-window recovery tests


def test_state_manager_recovers_tmp_over_bak_when_state_absent(tmp_path: Path) -> None:
    """Crash between bak-rotate and tmp->state rename: tmp is newer, must win."""
    manager = StateManager(tmp_path)

    # Simulate: bak holds an older save.
    bak_content = {"version": 3, "value": "old"}
    manager.backup_path.write_text(json.dumps(bak_content), encoding="utf-8")

    # Simulate: a pid-suffixed tmp holds a newer save (written after the bak rotation).
    tmp_path_file = tmp_path / f"{STATE_TMP_PREFIX}{os.getpid()}{STATE_TMP_SUFFIX}"
    newer_content = {"version": 3, "value": "new"}
    tmp_path_file.write_text(json.dumps(newer_content), encoding="utf-8")
    # Ensure tmp mtime is clearly newer than bak.
    bak_stat = manager.backup_path.stat()
    os.utime(tmp_path_file, (bak_stat.st_atime + 10, bak_stat.st_mtime + 10))

    # state_path must not exist (crash window scenario).
    assert not manager.state_path.exists()

    result = manager.load()

    assert result["value"] == "new"


def test_state_manager_falls_back_to_bak_when_tmp_is_absent(tmp_path: Path) -> None:
    """No tmp present: bak must be used."""
    manager = StateManager(tmp_path)

    bak_content = {"version": 4, "value": "bak_only"}
    manager.backup_path.write_text(json.dumps(bak_content), encoding="utf-8")

    assert not manager.state_path.exists()

    result = manager.load()

    assert result["value"] == "bak_only"


def test_state_manager_save_uses_pid_suffixed_tmp(tmp_path: Path) -> None:
    """save() must write through a per-process tmp to avoid write-write races."""
    manager = StateManager(tmp_path)

    manager.save({"value": "round_trip"})

    assert manager.load()["value"] == "round_trip"
    # After successful save the pid-tmp is renamed to state; no orphan tmp remains.
    orphan_tmps = [
        p
        for p in tmp_path.iterdir()
        if p.name.startswith(STATE_TMP_PREFIX) and p.name.endswith(STATE_TMP_SUFFIX)
    ]
    assert orphan_tmps == [], f"Unexpected tmp files left: {orphan_tmps}"


def test_state_manager_two_saves_produce_state_and_backup(tmp_path: Path) -> None:
    """Second save rotates first save into bak; both files must exist."""
    manager = StateManager(tmp_path)

    manager.save({"value": "first"})
    manager.save({"value": "second"})

    assert (tmp_path / STATE_FILENAME).exists()
    assert manager.backup_path.exists()
    assert manager.load()["value"] == "second"


# ISS-023: stale crash-remnant tmp cleanup tests


def test_save_removes_stale_other_pid_tmp(tmp_path: Path, monkeypatch) -> None:
    """save() must remove other-process tmp files older than the committed state."""
    manager = StateManager(tmp_path)

    # Simulate a crashed process that left a tmp with a different PID.
    fake_pid = os.getpid() + 9999
    stale_tmp = tmp_path / f"{STATE_TMP_PREFIX}{fake_pid}{STATE_TMP_SUFFIX}"
    stale_tmp.write_text(json.dumps({"value": "stale"}), encoding="utf-8")

    # Make the stale tmp clearly older than now so it will be behind the committed state.
    old_time = 1_000_000.0  # epoch seconds – safely in the past
    os.utime(stale_tmp, (old_time, old_time))

    manager.save({"value": "current"})

    assert not stale_tmp.exists(), "Stale other-pid tmp should have been cleaned up after save."


def test_save_preserves_concurrent_newer_tmp(tmp_path: Path) -> None:
    """save() must NOT remove another pid's tmp whose mtime >= the committed state."""
    manager = StateManager(tmp_path)

    manager.save({"value": "current"})

    # Simulate a concurrent process writing a tmp *after* the commit.
    fake_pid = os.getpid() + 9999
    concurrent_tmp = tmp_path / f"{STATE_TMP_PREFIX}{fake_pid}{STATE_TMP_SUFFIX}"
    concurrent_tmp.write_text(json.dumps({"value": "concurrent"}), encoding="utf-8")
    # Set mtime to be newer than the just-committed state.
    committed_mtime = manager.state_path.stat().st_mtime
    os.utime(concurrent_tmp, (committed_mtime + 10, committed_mtime + 10))

    # Trigger another save; the concurrent tmp is newer, must survive.
    manager.save({"value": "second"})

    assert concurrent_tmp.exists(), "Concurrent newer tmp must not be deleted."
    concurrent_tmp.unlink()  # manual cleanup so tmp_path stays tidy


def test_stale_other_pid_tmp_older_than_bak_does_not_elevate(tmp_path: Path) -> None:
    """Regression: a stale crash-remnant tmp must not be elevated over bak during load.

    Scenario: bak exists and is newer than the stale tmp.  load() must use bak,
    not the older stale tmp from a crashed process.
    """
    manager = StateManager(tmp_path)

    # Write a bak that represents a proper save.
    bak_content = {"value": "bak_good"}
    manager.backup_path.write_text(json.dumps(bak_content), encoding="utf-8")
    bak_mtime = manager.backup_path.stat().st_mtime

    # Leave a stale other-pid tmp that is older than bak.
    fake_pid = os.getpid() + 9999
    stale_tmp = tmp_path / f"{STATE_TMP_PREFIX}{fake_pid}{STATE_TMP_SUFFIX}"
    stale_tmp.write_text(json.dumps({"value": "stale_remnant"}), encoding="utf-8")
    os.utime(stale_tmp, (bak_mtime - 10, bak_mtime - 10))

    # No state_path: triggers _load_without_state.
    assert not manager.state_path.exists()

    result = manager.load()

    assert result["value"] == "bak_good", (
        "bak must win over a stale tmp that is older than it"
    )


def test_save_multi_instance_simulation(tmp_path: Path, monkeypatch) -> None:
    """Simulate two concurrent instances writing their own pid-suffixed tmps.

    Instance A commits first.  After A's commit the stale B tmp (older than
    A's state) is removed.  Instance B's save then runs and commits cleanly.
    """
    # --- Instance A ---
    manager_a = StateManager(tmp_path)
    manager_a.save({"value": "a"})
    committed_mtime_a = manager_a.state_path.stat().st_mtime

    # --- Simulate Instance B leaving a stale tmp before A committed ---
    pid_b = os.getpid() + 8888
    stale_b_tmp = tmp_path / f"{STATE_TMP_PREFIX}{pid_b}{STATE_TMP_SUFFIX}"
    stale_b_tmp.write_text(json.dumps({"value": "b_stale"}), encoding="utf-8")
    os.utime(stale_b_tmp, (committed_mtime_a - 5, committed_mtime_a - 5))

    # Trigger A's second save, which should clean up B's stale tmp.
    manager_a.save({"value": "a2"})

    assert not stale_b_tmp.exists(), "A's second save must remove stale B tmp."

    # --- Instance B now completes its save using a different pid ---
    monkeypatch.setattr(os, "getpid", lambda: pid_b)
    manager_b = StateManager(tmp_path)
    manager_b.save({"value": "b_final"})

    assert manager_b.load()["value"] == "b_final"


# ---------------------------------------------------------------------------
# ISS-019: work_dir UNC rejection and path normalisation
# ---------------------------------------------------------------------------


class TestWorkDirFromRequest:
    def test_unc_backslash_prefix_is_rejected(self) -> None:
        """\\\\server\\share style UNC paths must raise ValueError."""
        with pytest.raises(ValueError, match="ネットワークパス"):
            work_dir_from_request({"work_dir": r"\\server\share\work"})

    def test_unc_forward_slash_prefix_is_rejected(self) -> None:
        """//server/share style UNC paths must raise ValueError."""
        with pytest.raises(ValueError, match="ネットワークパス"):
            work_dir_from_request({"work_dir": "//server/share/work"})

    def test_local_absolute_path_is_accepted(self, tmp_path: Path) -> None:
        """A regular local absolute path must be accepted and resolved."""
        result = work_dir_from_request({"work_dir": str(tmp_path)})
        assert result == tmp_path.resolve()

    def test_local_path_is_resolved_to_absolute(self, tmp_path: Path, monkeypatch) -> None:
        """A relative-looking path is passed through Path.resolve()."""
        # Use an absolute path that contains a non-canonical segment to verify resolution.
        canonical = tmp_path.resolve()
        non_canonical = str(canonical) + os.sep + ".."
        result = work_dir_from_request({"work_dir": non_canonical})
        # resolve() should collapse the trailing /.. component.
        assert ".." not in result.parts

    def test_missing_work_dir_falls_back_to_default(self, monkeypatch, tmp_path: Path) -> None:
        """An empty or absent work_dir key must return default_work_dir()."""
        monkeypatch.setenv("PDF_ORGANIZER_WORK_DIR", str(tmp_path / "default"))
        result_empty = work_dir_from_request({"work_dir": ""})
        result_absent = work_dir_from_request({})
        assert result_empty == tmp_path / "default"
        assert result_absent == tmp_path / "default"

    def test_unc_error_message_suggests_local_path(self) -> None:
        """The ValueError message must mention local folder guidance in Japanese."""
        with pytest.raises(ValueError) as exc_info:
            work_dir_from_request({"work_dir": r"\\nas\share"})
        assert "ローカルフォルダ" in str(exc_info.value)

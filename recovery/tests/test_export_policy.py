from __future__ import annotations

from pathlib import Path

from pdf_splitter_tool.export_policy import ExportPathPolicy, unique_output_path


def test_unique_output_path_uses_requested_path_when_available(tmp_path: Path) -> None:
    requested = tmp_path / "01_02_003.pdf"

    assert unique_output_path(requested, set()) == requested


def test_unique_output_path_skips_existing_file_with_numbered_suffix(tmp_path: Path) -> None:
    requested = tmp_path / "01_02_003.pdf"
    requested.write_bytes(b"existing")

    assert unique_output_path(requested, set()) == tmp_path / "01_02_003_2.pdf"


def test_unique_output_path_skips_reserved_paths_in_same_preflight(tmp_path: Path) -> None:
    requested = tmp_path / "01_02_003.pdf"
    reserved = {requested, tmp_path / "01_02_003_2.pdf"}

    assert unique_output_path(requested, reserved) == tmp_path / "01_02_003_3.pdf"


def test_export_path_policy_reserves_numbered_paths_for_same_preflight(tmp_path: Path) -> None:
    requested = tmp_path / "01_02_003.pdf"
    policy = ExportPathPolicy()

    assert policy.reserve_output_path(requested) == requested
    assert policy.reserve_output_path(requested) == tmp_path / "01_02_003_2.pdf"
    assert policy.reserve_output_path(requested) == tmp_path / "01_02_003_3.pdf"

from __future__ import annotations

import pytest

from pdf_splitter_tool.domain import (
    METADATA_REQUIRED_KEYS,
    YOSHIDA_FILENAME_TEMPLATE,
    build_yoshida_filename_preview,
)


def test_domain_exposes_yoshida_business_constants() -> None:
    assert METADATA_REQUIRED_KEYS == ("box_no", "binder_no", "seq")
    assert YOSHIDA_FILENAME_TEMPLATE == "{box_no:0>2}_{binder_no:0>2}_{seq:0>3}.pdf"


@pytest.mark.parametrize(
    "metadata",
    [
        {"box_no": "1", "binder_no": "2", "seq": "3"},
        {"box_no": "12", "binder_no": "34", "seq": "56"},
        {"box_no": "1/2", "binder_no": "3:4", "seq": "5*6"},
    ],
)
def test_yoshida_filename_preview_builds_expected_filename(metadata: dict[str, object]) -> None:
    result = build_yoshida_filename_preview(metadata)

    assert result.ok
    assert result.raw_filename
    assert result.normalized_filename.endswith(".pdf")


def test_yoshida_filename_preview_zero_pads_box_binder_and_seq() -> None:
    result = build_yoshida_filename_preview({"box_no": "1", "binder_no": "2", "seq": "3"})

    assert result.ok
    assert result.raw_filename == "01_02_003.pdf"
    assert result.normalized_filename == "01_02_003.pdf"


def test_yoshida_filename_preview_sanitizes_windows_invalid_filename_chars() -> None:
    result = build_yoshida_filename_preview({"box_no": "1/2", "binder_no": "3:4", "seq": "5*6"})

    assert result.ok
    assert result.raw_filename == "1/2_3:4_5*6.pdf"
    assert result.normalized_filename == "1_2_3_4_5_6.pdf"
    assert "filename_sanitized" in result.warnings


@pytest.mark.parametrize(
    "metadata",
    [
        {},
        {"box_no": "1", "binder_no": "", "seq": "3"},
        {"box_no": " ", "binder_no": "2", "seq": "3"},
    ],
)
def test_yoshida_filename_preview_reports_missing_fields(metadata: dict[str, object]) -> None:
    result = build_yoshida_filename_preview(metadata)

    assert not result.ok
    assert result.raw_filename == ""
    assert result.normalized_filename == ""
    assert result.errors

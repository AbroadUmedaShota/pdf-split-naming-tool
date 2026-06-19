from __future__ import annotations

import pytest

from pdf_splitter_tool.domain import (
    METADATA_REQUIRED_KEYS,
    YOSHIDA_FILENAME_TEMPLATE,
    build_yoshida_filename_preview,
    sanitize_filename_with_warnings,
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


# --- 追加項目(affix): 先頭/末尾への任意挿入 ---

COMPANY_PREFIX = {"key": "company", "label": "会社名", "position": "prefix"}
DOC_SUFFIX = {"key": "doc", "label": "契約書名", "position": "suffix"}


def test_affix_prefix_and_suffix_are_inserted_around_fixed_tokens() -> None:
    metadata = {"box_no": "1", "binder_no": "2", "seq": "3", "company": "A商事", "doc": "基本契約"}
    result = build_yoshida_filename_preview(metadata, (COMPANY_PREFIX, DOC_SUFFIX))

    assert result.ok
    assert result.raw_filename == "A商事_01_02_003_基本契約.pdf"
    assert result.normalized_filename == "A商事_01_02_003_基本契約.pdf"


def test_affix_empty_value_is_dropped_with_its_separator() -> None:
    metadata = {"box_no": "1", "binder_no": "2", "seq": "3", "company": "A商事"}
    result = build_yoshida_filename_preview(metadata, (COMPANY_PREFIX, DOC_SUFFIX))

    assert result.raw_filename == "A商事_01_02_003.pdf"


def test_affix_absent_keeps_backward_compatible_filename() -> None:
    metadata = {"box_no": "1", "binder_no": "2", "seq": "3"}

    assert build_yoshida_filename_preview(metadata, (COMPANY_PREFIX, DOC_SUFFIX)).raw_filename == "01_02_003.pdf"
    assert build_yoshida_filename_preview(metadata).raw_filename == "01_02_003.pdf"


def test_affix_same_position_keeps_definition_order() -> None:
    defs = (
        {"key": "company", "label": "会社名", "position": "prefix"},
        {"key": "doc", "label": "契約書名", "position": "prefix"},
    )
    metadata = {"box_no": "1", "binder_no": "2", "seq": "3", "company": "X", "doc": "Y"}

    assert build_yoshida_filename_preview(metadata, defs).raw_filename == "X_Y_01_02_003.pdf"


def test_affix_does_not_affect_required_validation() -> None:
    metadata = {"box_no": "", "binder_no": "2", "seq": "3", "company": "A商事"}
    result = build_yoshida_filename_preview(metadata, (COMPANY_PREFIX,))

    assert not result.ok
    assert "missing_required:box_no" in result.errors


# --- 連番(seq)の桁数(seq_digits)可変 ---


def test_seq_digits_controls_zero_padding() -> None:
    metadata = {"box_no": "1", "binder_no": "2", "seq": "3"}

    assert build_yoshida_filename_preview(metadata).raw_filename == "01_02_003.pdf"  # 既定3桁
    assert build_yoshida_filename_preview(metadata, (), 4).raw_filename == "01_02_0003.pdf"
    assert build_yoshida_filename_preview(metadata, (), 2).raw_filename == "01_02_03.pdf"


def test_seq_digits_invalid_or_out_of_range_is_clamped() -> None:
    metadata = {"box_no": "1", "binder_no": "2", "seq": "3"}

    assert build_yoshida_filename_preview(metadata, (), "bad").raw_filename == "01_02_003.pdf"  # 不正→既定3
    assert build_yoshida_filename_preview(metadata, (), 0).raw_filename == "01_02_3.pdf"  # 下限1
    # box/binderの桁数(2)はseq_digitsの影響を受けない
    assert build_yoshida_filename_preview({"box_no": "1", "binder_no": "2", "seq": "3"}, (), 5).raw_filename == "01_02_00003.pdf"


# --- sanitize_filename_with_warnings: 制御文字・全角禁止文字・stem末尾ドット (#84) ---


@pytest.mark.parametrize(
    "char,label",
    [
        ("\x00", "null byte"),
        ("\n", "newline"),
        ("\r", "carriage return"),
        ("\t", "tab"),
        ("\x01", "SOH control char"),
        ("\x1f", "US control char (highest in 0x00-0x1f range)"),
    ],
)
def test_sanitize_replaces_control_characters_with_underscore(char: str, label: str) -> None:
    filename = f"name{char}file.pdf"
    result, warnings = sanitize_filename_with_warnings(filename)
    assert result == "name_file.pdf", f"Failed for {label}: got {result!r}"
    assert "filename_sanitized" in warnings


@pytest.mark.parametrize(
    "char,label",
    [
        ("＜", "fullwidth less-than sign"),
        ("＞", "fullwidth greater-than sign"),
        ("：", "fullwidth colon"),
        ("＂", "fullwidth quotation mark"),
        ("／", "fullwidth solidus"),
        ("＼", "fullwidth reverse solidus"),
        ("｜", "fullwidth vertical line"),
        ("？", "fullwidth question mark"),
        ("＊", "fullwidth asterisk"),
    ],
)
def test_sanitize_replaces_fullwidth_forbidden_chars_with_underscore(char: str, label: str) -> None:
    filename = f"name{char}file.pdf"
    result, warnings = sanitize_filename_with_warnings(filename)
    assert result == "name_file.pdf", f"Failed for {label} (U+{ord(char):04X}): got {result!r}"
    assert "filename_sanitized" in warnings


def test_sanitize_keeps_non_forbidden_fullwidth_chars_intact() -> None:
    # Full-width alphanumerics and Japanese text must not be altered.
    filename = "日本語テスト_ＡＢＣ.pdf"
    result, _ = sanitize_filename_with_warnings(filename)
    assert result == filename


@pytest.mark.parametrize(
    "filename,expected,label",
    [
        ("name..pdf", "name.pdf", "single trailing dot on stem"),
        ("name. .pdf", "name.pdf", "trailing dot-space on stem"),
        ("name   .pdf", "name.pdf", "trailing spaces on stem"),
        ("report.pdf. ", "report.pdf", "trailing space-dot after extension"),
        ("report.pdf.", "report.pdf", "trailing dot after extension"),
    ],
)
def test_sanitize_strips_trailing_dot_space_from_stem(filename: str, expected: str, label: str) -> None:
    result, _ = sanitize_filename_with_warnings(filename)
    assert result == expected, f"Failed for {label!r}: got {result!r}"

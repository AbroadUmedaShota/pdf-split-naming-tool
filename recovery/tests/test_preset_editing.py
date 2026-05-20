from __future__ import annotations

import pytest

from pdf_splitter_tool.preset_editing import build_preset_from_editor, format_field_rows, parse_field_rows, parse_keywords


def test_parse_field_rows_supports_required_and_optional_fields() -> None:
    fields = parse_field_rows(
        "\n".join(
            [
                "box_no|箱No|true|",
                "binder_no|バインダーNo|必須|",
                "company|会社名|false|",
            ]
        )
    )

    assert [field.key for field in fields] == ["box_no", "binder_no", "company"]
    assert [field.required for field in fields] == [True, True, False]
    assert format_field_rows(fields).splitlines()[0] == "box_no|箱No|true|"


def test_parse_field_rows_rejects_duplicate_keys() -> None:
    with pytest.raises(ValueError, match="重複"):
        parse_field_rows("seq|連番|true|\nseq|連番2|false|")


def test_parse_keywords_deduplicates_comma_and_newline_values() -> None:
    assert parse_keywords("契約, 箱\n契約\nbinder") == ("契約", "箱", "binder")


def test_build_preset_from_editor_creates_custom_preset() -> None:
    preset = build_preset_from_editor(
        preset_id="future-case",
        name="Future Case",
        field_rows="box_no|箱No|true|\nseq|連番|true|1",
        naming_template="{box_no}_{seq}.pdf",
        extraction_keywords="契約, agreement",
        blank_threshold="0.98",
        index_threshold="0.7",
    )

    assert preset.id == "future-case"
    assert preset.naming_template == "{box_no}_{seq}.pdf"
    assert preset.extraction_keywords == ("契約", "agreement")
    assert preset.blank_threshold == 0.98
    assert preset.fields[1].default == "1"


def test_build_preset_from_editor_rejects_template_without_pdf_extension() -> None:
    with pytest.raises(ValueError, match=".pdf"):
        build_preset_from_editor(
            preset_id="future-case",
            name="Future Case",
            field_rows="seq|連番|true|",
            naming_template="{seq}.txt",
            extraction_keywords="",
            blank_threshold="0.98",
            index_threshold="0.7",
        )

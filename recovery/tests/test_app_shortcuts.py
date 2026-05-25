from pdf_splitter_tool.app import STEP2_DETAIL_TAB_LABELS, TEXT_WIDGET_CLASSES


def test_text_widget_classes_block_global_shortcuts() -> None:
    assert "Entry" in TEXT_WIDGET_CLASSES
    assert "TEntry" in TEXT_WIDGET_CLASSES
    assert "Text" in TEXT_WIDGET_CLASSES
    assert "TCombobox" in TEXT_WIDGET_CLASSES


def test_step2_detail_tabs_are_named_for_smoke_verification() -> None:
    assert STEP2_DETAIL_TAB_LABELS == ("検出", "候補", "OCR本文", "操作")

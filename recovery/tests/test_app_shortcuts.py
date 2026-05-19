from pdf_splitter_tool.app import TEXT_WIDGET_CLASSES


def test_text_widget_classes_block_global_shortcuts() -> None:
    assert "Entry" in TEXT_WIDGET_CLASSES
    assert "TEntry" in TEXT_WIDGET_CLASSES
    assert "Text" in TEXT_WIDGET_CLASSES
    assert "TCombobox" in TEXT_WIDGET_CLASSES

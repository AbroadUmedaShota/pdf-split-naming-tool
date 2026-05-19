from pathlib import Path

from pdf_splitter_tool.presets import PresetRepository, YOSHIDA_ELSIS_PRESET, find_preset
from pdf_splitter_tool.state import StateManager


def test_preset_repository_saves_and_loads_yoshida(tmp_path: Path) -> None:
    path = tmp_path / "presets.json"
    repo = PresetRepository(path)
    presets, active_id = repo.load()
    assert active_id == YOSHIDA_ELSIS_PRESET.id

    repo.save(presets, YOSHIDA_ELSIS_PRESET.id)
    loaded, loaded_active_id = repo.load()
    preset = find_preset(loaded, loaded_active_id)

    assert loaded_active_id == YOSHIDA_ELSIS_PRESET.id
    assert preset.naming_template == "{box_no:0>2}_{binder_no:0>2}_{seq:0>3}.pdf"
    assert [field.key for field in preset.fields] == ["box_no", "binder_no", "seq", "company", "doc"]
    assert [field.required for field in preset.fields] == [True, True, True, False, False]


def test_state_manager_writes_state_and_backup(tmp_path: Path) -> None:
    manager = StateManager(tmp_path)

    manager.save({"version": 1, "value": "first"})
    manager.save({"version": 1, "value": "second"})

    assert manager.load()["value"] == "second"
    assert manager.backup_path.exists()

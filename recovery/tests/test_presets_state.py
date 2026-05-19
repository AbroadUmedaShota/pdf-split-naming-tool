import json
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
    assert preset.name == "吉田エルシス"
    assert preset.naming_template == "{box_no:0>2}_{binder_no:0>2}_{seq:0>3}.pdf"
    assert [field.key for field in preset.fields] == ["box_no", "binder_no", "seq", "company", "doc"]
    assert [field.label for field in preset.fields] == [
        "箱No",
        "バインダーNo",
        "連番",
        "会社名（任意）",
        "契約書名（任意）",
    ]
    assert [field.required for field in preset.fields] == [True, True, True, False, False]


def test_preset_repository_refreshes_builtin_yoshida_labels(tmp_path: Path) -> None:
    path = tmp_path / "presets.json"
    path.write_text(
        json.dumps(
            {
                "active_preset_id": YOSHIDA_ELSIS_PRESET.id,
                "presets": [
                    {
                        "id": YOSHIDA_ELSIS_PRESET.id,
                        "name": "Yoshida Elsis",
                        "fields": [
                            {"key": "box_no", "label": "Box No", "required": True},
                            {"key": "binder_no", "label": "Binder No", "required": True},
                            {"key": "seq", "label": "Sequence", "required": True},
                            {"key": "company", "label": "Company", "required": False},
                            {"key": "doc", "label": "Document", "required": False},
                        ],
                        "naming_template": "{box_no:0>2}_{binder_no:0>2}_{seq:0>3}.pdf",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    presets, active_id = PresetRepository(path).load()
    preset = find_preset(presets, active_id)

    assert preset.name == "吉田エルシス"
    assert [field.label for field in preset.fields] == [
        "箱No",
        "バインダーNo",
        "連番",
        "会社名（任意）",
        "契約書名（任意）",
    ]


def test_state_manager_writes_state_and_backup(tmp_path: Path) -> None:
    manager = StateManager(tmp_path)

    manager.save({"version": 1, "value": "first"})
    manager.save({"version": 1, "value": "second"})

    assert manager.load()["value"] == "second"
    assert manager.backup_path.exists()

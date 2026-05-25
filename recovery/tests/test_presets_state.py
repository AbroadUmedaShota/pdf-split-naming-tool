import json
from pathlib import Path

from pdf_splitter_tool.models import MetadataField, Preset
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
    assert preset.name == "ヨシダエルシス"
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

    assert preset.name == "ヨシダエルシス"
    assert [field.label for field in preset.fields] == [
        "箱No",
        "バインダーNo",
        "連番",
        "会社名（任意）",
        "契約書名（任意）",
    ]


def test_preset_repository_saves_and_loads_custom_preset(tmp_path: Path) -> None:
    path = tmp_path / "presets.json"
    repo = PresetRepository(path)
    presets, _active_id = repo.load()
    custom = Preset(
        id="future-case",
        name="Future Case",
        fields=(MetadataField("box_no", "箱No", required=True), MetadataField("seq", "連番", required=True)),
        naming_template="{box_no}_{seq}.pdf",
        extraction_keywords=("契約", "agreement"),
        blank_threshold=0.98,
        index_threshold=0.75,
    )

    repo.save([*presets, custom], custom.id)
    loaded, loaded_active_id = repo.load()
    loaded_custom = find_preset(loaded, loaded_active_id)

    assert loaded_active_id == custom.id
    assert loaded_custom.name == "Future Case"
    assert loaded_custom.extraction_keywords == ("契約", "agreement")
    assert loaded_custom.blank_threshold == 0.98


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
    assert json.loads(manager.state_path.read_text(encoding="utf-8"))["value"] == "backup"


def test_state_manager_loads_backup_when_state_file_is_missing(tmp_path: Path) -> None:
    manager = StateManager(tmp_path)
    manager.backup_path.write_text(json.dumps({"version": 2, "value": "backup"}), encoding="utf-8")

    assert manager.load()["value"] == "backup"
    assert manager.state_path.exists()
    assert manager.backup_path.exists()


def test_state_manager_loads_tmp_when_state_and_backup_are_missing(tmp_path: Path) -> None:
    manager = StateManager(tmp_path)
    manager.tmp_path.write_text(json.dumps({"version": 2, "value": "tmp"}), encoding="utf-8")

    assert manager.load()["value"] == "tmp"
    assert manager.state_path.exists()
    assert not manager.tmp_path.exists()


def test_state_manager_loads_tmp_after_archiving_broken_state_without_backup(tmp_path: Path) -> None:
    manager = StateManager(tmp_path)
    manager.state_path.write_text("{broken current", encoding="utf-8")
    manager.tmp_path.write_text(json.dumps({"version": 2, "value": "tmp"}), encoding="utf-8")

    assert manager.load()["value"] == "tmp"

    archived = list(tmp_path.glob("_pdf_split_state.json.corrupt*"))
    assert len(archived) == 1
    assert archived[0].read_text(encoding="utf-8") == "{broken current"
    assert manager.state_path.exists()
    assert not manager.tmp_path.exists()


def test_state_manager_falls_back_to_backup_when_state_schema_is_invalid(tmp_path: Path) -> None:
    manager = StateManager(tmp_path)

    manager.save({"version": 2, "value": "backup"})
    manager.save({"version": 2, "value": "current"})
    manager.state_path.write_text(json.dumps(["not", "a", "state", "object"]), encoding="utf-8")

    assert manager.load()["value"] == "backup"


def test_state_manager_does_not_overwrite_backup_with_broken_state(tmp_path: Path) -> None:
    manager = StateManager(tmp_path)

    manager.save({"version": 2, "value": "backup"})
    manager.save({"version": 2, "value": "current"})
    manager.state_path.write_text("{broken", encoding="utf-8")

    manager.save({"version": 2, "value": "new"})

    assert manager.load()["value"] == "new"
    assert json.loads(manager.backup_path.read_text(encoding="utf-8"))["value"] == "backup"
    archived = list(tmp_path.glob("_pdf_split_state.json.corrupt*"))
    assert len(archived) == 1
    assert archived[0].read_text(encoding="utf-8") == "{broken"


def test_state_manager_archives_broken_state_and_backup_when_both_are_unreadable(tmp_path: Path) -> None:
    manager = StateManager(tmp_path)
    manager.state_path.write_text("{broken current", encoding="utf-8")
    manager.backup_path.write_text("{broken backup", encoding="utf-8")

    assert manager.load() == {}

    archived = sorted(path.read_text(encoding="utf-8") for path in tmp_path.glob("_pdf_split_state*.corrupt*"))
    assert archived == ["{broken backup", "{broken current"]
    assert not manager.state_path.exists()
    assert not manager.backup_path.exists()

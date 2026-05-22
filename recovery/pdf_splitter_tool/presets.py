from __future__ import annotations

import json
from pathlib import Path

from .models import MetadataField, Preset


YOSHIDA_ELSIS_PRESET = Preset(
    id="yoshida-elsis",
    name="ヨシダエルシス",
    fields=(
        MetadataField("box_no", "箱No", required=True),
        MetadataField("binder_no", "バインダーNo", required=True),
        MetadataField("seq", "連番", required=True),
        MetadataField("company", "会社名（任意）", required=False),
        MetadataField("doc", "契約書名（任意）", required=False),
    ),
    naming_template="{box_no:0>2}_{binder_no:0>2}_{seq:0>3}.pdf",
    extraction_keywords=("箱", "バインダー", "契約", "契約書", "agreement"),
)

LEGACY_PRESET = Preset(
    id="legacy-full",
    name="Legacy full metadata",
    fields=(
        MetadataField("box_no", "Box No", required=True),
        MetadataField("binder_no", "Binder No", required=True),
        MetadataField("seq", "Sequence", required=True),
        MetadataField("company", "Company", required=True),
        MetadataField("doc", "Document", required=True),
    ),
    naming_template="{box_no:0>2}_{binder_no:0>2}_{seq:0>3}_{company}_{doc}.pdf",
    extraction_keywords=("company", "contract", "agreement"),
)

DEFAULT_PRESETS = (YOSHIDA_ELSIS_PRESET, LEGACY_PRESET)
DEFAULT_PRESET_IDS = {preset.id for preset in DEFAULT_PRESETS}


class PresetRepository:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> tuple[list[Preset], str]:
        if not self.path.exists():
            return list(DEFAULT_PRESETS), YOSHIDA_ELSIS_PRESET.id

        data = json.loads(self.path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            presets = [Preset.from_dict(item) for item in data]
            active_id = presets[0].id if presets else YOSHIDA_ELSIS_PRESET.id
            return self._with_defaults(presets), active_id

        presets = [Preset.from_dict(item) for item in data.get("presets", [])]
        active_id = str(data.get("active_preset_id", YOSHIDA_ELSIS_PRESET.id))
        presets = self._with_defaults(presets)
        if active_id not in {preset.id for preset in presets}:
            active_id = YOSHIDA_ELSIS_PRESET.id
        return presets, active_id

    def save(self, presets: list[Preset], active_preset_id: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "active_preset_id": active_preset_id,
            "presets": [preset.to_dict() for preset in presets],
        }
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(self.path)

    def _with_defaults(self, presets: list[Preset]) -> list[Preset]:
        by_id = {preset.id: preset for preset in presets}
        for preset in DEFAULT_PRESETS:
            by_id[preset.id] = preset
        return list(by_id.values())


def find_preset(presets: list[Preset], preset_id: str) -> Preset:
    for preset in presets:
        if preset.id == preset_id:
            return preset
    return YOSHIDA_ELSIS_PRESET

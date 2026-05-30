from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DESKTOP = ROOT / "apps" / "desktop"


def test_desktop_shell_uses_next_static_export_for_tauri() -> None:
    package_json = json.loads((DESKTOP / "package.json").read_text(encoding="utf-8"))
    next_config = (DESKTOP / "next.config.mjs").read_text(encoding="utf-8")
    tauri_config = json.loads((DESKTOP / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))

    assert package_json["scripts"]["build"] == "next build"
    assert package_json["scripts"]["typecheck"] == "tsc --noEmit"
    assert package_json["dependencies"]["next"].startswith("^16.")
    assert "output: 'export'" in next_config
    assert tauri_config["build"]["frontendDist"] == "../out"
    assert tauri_config["build"]["beforeBuildCommand"] == "npm run build"


def test_desktop_tauri_exposes_python_sidecar_bridge() -> None:
    cargo_toml = (DESKTOP / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8")
    lib_rs = (DESKTOP / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")

    assert "serde_json" in cargo_toml
    assert "#[tauri::command]" in lib_rs
    assert "run_sidecar" in lib_rs
    assert "pdf_splitter_tool" in lib_rs
    assert "tauri::generate_handler![run_sidecar]" in lib_rs


def test_desktop_tauri_enables_dialog_plugin_for_local_file_selection() -> None:
    package_json = json.loads((DESKTOP / "package.json").read_text(encoding="utf-8"))
    cargo_toml = (DESKTOP / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8")
    lib_rs = (DESKTOP / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")

    assert "@tauri-apps/plugin-dialog" in package_json["dependencies"]
    assert "tauri-plugin-dialog" in cargo_toml
    assert "tauri_plugin_dialog::init()" in lib_rs


def test_desktop_sidecar_contract_is_minimal_mvp() -> None:
    sidecar_contract = (DESKTOP / "lib" / "sidecar.ts").read_text(encoding="utf-8")

    for command in ("pdf_info", "page_preview", "preflight", "export", "state_load", "state_save"):
        assert f'"{command}"' in sidecar_contract
    for removed in ("page_text", "presets", "history", "reuse_existing", "skip", "output_actions"):
        assert f'"{removed}"' not in sidecar_contract


def test_desktop_sidecar_contract_documents_mvp_response_shapes() -> None:
    sidecar_contract = (DESKTOP / "lib" / "sidecar.ts").read_text(encoding="utf-8")

    assert "export type SidecarResponse" in sidecar_contract
    assert "export type SidecarPreviewResponse" in sidecar_contract
    assert "image_data_url: string" in sidecar_contract
    assert "summary: SidecarExportSummary" in sidecar_contract
    assert '"created" | "failed"' in sidecar_contract
    assert "state: AppPersistedState" in sidecar_contract

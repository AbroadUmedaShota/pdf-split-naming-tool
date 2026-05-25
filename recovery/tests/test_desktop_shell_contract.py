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


def test_desktop_shell_uses_readable_japanese_window_title() -> None:
    tauri_config = json.loads((DESKTOP / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))

    assert tauri_config["productName"] == "PDF整理ツール"
    assert tauri_config["app"]["windows"][0]["title"] == "PDF整理ツール"
    assert "�" not in tauri_config["productName"]


def test_desktop_tauri_exposes_python_sidecar_bridge() -> None:
    cargo_toml = (DESKTOP / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8")
    lib_rs = (DESKTOP / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")

    assert "serde_json" in cargo_toml
    assert "#[tauri::command]" in lib_rs
    assert "run_sidecar" in lib_rs
    assert "pdf_splitter_tool" in lib_rs
    assert "tauri::generate_handler![run_sidecar]" in lib_rs


def test_desktop_tauri_forces_utf8_python_sidecar_json() -> None:
    lib_rs = (DESKTOP / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")

    assert 'env("PYTHONIOENCODING", "utf-8")' in lib_rs
    assert 'env("PYTHONUTF8", "1")' in lib_rs


def test_desktop_shell_documents_sidecar_command_contracts() -> None:
    sidecar_contract = (DESKTOP / "lib" / "sidecar.ts").read_text(encoding="utf-8")

    for command in ("pdf_info", "page_text", "presets", "history", "preflight", "export"):
        assert f'"{command}"' in sidecar_contract


def test_desktop_sidecar_contract_supports_work_dir_and_output_actions() -> None:
    sidecar_contract = (DESKTOP / "lib" / "sidecar.ts").read_text(encoding="utf-8")

    assert "work_dir?: string" in sidecar_contract
    assert "output_actions?: Record<string, SidecarOutputAction>" in sidecar_contract
    assert '"create_unique"' in sidecar_contract
    assert '"create" | "reuse_existing" | "skip"' not in sidecar_contract
    assert '"reuse_existing"' in sidecar_contract
    assert '"skip"' in sidecar_contract


def test_desktop_sidecar_contract_documents_response_shapes() -> None:
    sidecar_contract = (DESKTOP / "lib" / "sidecar.ts").read_text(encoding="utf-8")

    assert "export type SidecarResponse" in sidecar_contract
    assert "export type SidecarExportResponse" in sidecar_contract
    assert "history_error: SidecarError | null" in sidecar_contract
    assert "messages: string[]" in sidecar_contract
    assert "status: SidecarOutputStatus" in sidecar_contract
    assert '"created" | "reused" | "skipped" | "failed"' in sidecar_contract
    assert "source_pdf: string" in sidecar_contract
    assert "pages: string" in sidecar_contract


def test_desktop_sidecar_contract_exposes_typed_invoke_helper() -> None:
    sidecar_contract = (DESKTOP / "lib" / "sidecar.ts").read_text(encoding="utf-8")

    assert 'from "@tauri-apps/api/core"' in sidecar_contract
    assert "invokeSidecar" in sidecar_contract
    assert 'invoke<SidecarResponse>("run_sidecar", { request })' in sidecar_contract


def test_desktop_sidecar_history_items_allow_legacy_sparse_records() -> None:
    sidecar_contract = (DESKTOP / "lib" / "sidecar.ts").read_text(encoding="utf-8")

    assert "export type SidecarHistoryItem" in sidecar_contract
    assert "items: SidecarHistoryItem[]" in sidecar_contract
    assert "source_pdf?: string" in sidecar_contract
    assert "requested_filename?: string" in sidecar_contract
    assert "output_path?: string" in sidecar_contract

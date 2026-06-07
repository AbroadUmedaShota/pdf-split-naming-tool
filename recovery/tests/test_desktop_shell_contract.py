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
    assert tauri_config["bundle"]["icon"] == ["icons/icon.ico"]
    assert tauri_config["bundle"]["windows"]["wix"]["language"] == "ja-JP"


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


def test_desktop_tauri_enables_signed_github_release_updates() -> None:
    package_json = json.loads((DESKTOP / "package.json").read_text(encoding="utf-8"))
    cargo_toml = (DESKTOP / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8")
    lib_rs = (DESKTOP / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
    tauri_config = json.loads((DESKTOP / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
    capabilities = json.loads((DESKTOP / "src-tauri" / "capabilities" / "default.json").read_text(encoding="utf-8"))

    assert "@tauri-apps/plugin-updater" in package_json["dependencies"]
    assert "@tauri-apps/plugin-process" in package_json["dependencies"]
    assert "tauri-plugin-updater" in cargo_toml
    assert "tauri-plugin-process" in cargo_toml
    assert "tauri_plugin_updater::Builder::new().build()" in lib_rs
    assert "tauri_plugin_process::init()" in lib_rs
    assert tauri_config["bundle"]["createUpdaterArtifacts"] is True
    assert tauri_config["plugins"]["updater"]["pubkey"]
    assert tauri_config["plugins"]["updater"]["pubkey"] != "REPLACE_WITH_TAURI_UPDATER_PUBLIC_KEY"
    assert tauri_config["plugins"]["updater"]["endpoints"] == [
        "https://github.com/AbroadUmedaShota/pdf-split-naming-tool/releases/latest/download/latest.json"
    ]
    assert "updater:default" in capabilities["permissions"]
    assert "process:default" in capabilities["permissions"]


def test_desktop_ui_exposes_update_check_controls() -> None:
    page_tsx = (DESKTOP / "app" / "page.tsx").read_text(encoding="utf-8")
    update_ts = (DESKTOP / "lib" / "updates.ts").read_text(encoding="utf-8")

    assert "更新確認" in page_tsx
    assert "現在のバージョン" in page_tsx
    assert "インストール" in page_tsx
    assert "downloadAndInstall" in update_ts
    assert "relaunch" in update_ts


def test_release_docs_explain_updater_signing_and_latest_json() -> None:
    package_json = json.loads((DESKTOP / "package.json").read_text(encoding="utf-8"))
    release_doc = (DESKTOP / "RELEASE.md").read_text(encoding="utf-8")
    manifest_script = (DESKTOP / "scripts" / "create-updater-manifest.mjs").read_text(encoding="utf-8")

    assert package_json["scripts"]["release:manifest"] == "node scripts/create-updater-manifest.mjs"
    assert "TAURI_SIGNING_PRIVATE_KEY" in release_doc
    assert "Get-Content -Raw" in release_doc
    assert "npm run release:manifest" in release_doc
    assert "latest.json" in release_doc
    assert "GitHub Releases" in release_doc
    assert "公開リポジトリ" in release_doc
    assert "windows-x86_64" in manifest_script
    assert "latest.json" in manifest_script
    assert "encodeURIComponent" in manifest_script
    assert "release-assets" in manifest_script
    assert "pdf-organizer-desktop_" in manifest_script


def test_desktop_sidecar_contract_includes_legacy_step2_read_apis() -> None:
    sidecar_contract = (DESKTOP / "lib" / "sidecar.ts").read_text(encoding="utf-8")

    for command in (
        "pdf_info",
        "page_preview",
        "page_thumbnail",
        "page_text",
        "search_text",
        "search_highlights",
        "index_candidates",
        "blank_candidates",
        "preflight",
        "export",
        "state_load",
        "state_save",
    ):
        assert f'"{command}"' in sidecar_contract
    for removed in ("presets", "history", "reuse_existing", "skip", "output_actions"):
        assert f'"{removed}"' not in sidecar_contract


def test_desktop_sidecar_contract_documents_mvp_response_shapes() -> None:
    sidecar_contract = (DESKTOP / "lib" / "sidecar.ts").read_text(encoding="utf-8")

    assert "export type SidecarResponse" in sidecar_contract
    assert "export type SidecarPreviewResponse" in sidecar_contract
    assert "image_data_url: string" in sidecar_contract
    assert "export type SidecarPageTextResponse" in sidecar_contract
    assert "export type SidecarSearchTextResponse" in sidecar_contract
    assert "export type SidecarSearchHighlightsResponse" in sidecar_contract
    assert "export type SidecarIndexCandidatesResponse" in sidecar_contract
    assert "export type SidecarBlankCandidatesResponse" in sidecar_contract
    assert "summary: SidecarExportSummary" in sidecar_contract
    assert '"created" | "failed"' in sidecar_contract
    assert "state: AppPersistedState" in sidecar_contract

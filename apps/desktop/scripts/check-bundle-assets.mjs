import { existsSync, readdirSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

// Verify the artifacts that `npm run build:bundle` actually produces:
//   - PyInstaller sidecar exe (scripts/build-sidecar.ps1 output)
//   - Next.js static export (`output: 'export'` -> out/)
//
// This is the CI-facing check. It intentionally does NOT require the NSIS
// installer / .sig / latest.json, because build:bundle runs neither
// `tauri build` nor updater manifest generation. Installer/signature/manifest
// verification lives in check-release-assets.mjs (local, after `tauri build`).

const scriptDir = dirname(fileURLToPath(import.meta.url));
const appRoot = join(scriptDir, "..");

// build-sidecar.ps1 emits: src-tauri/resources/sidecar/pdf-splitter-sidecar.exe
const sidecarExeName = "pdf-splitter-sidecar.exe";
const sidecarExePath = join(appRoot, "src-tauri", "resources", "sidecar", sidecarExeName);

// next.config.mjs uses `output: 'export'`, so `next build` writes a static
// site to out/. tauri.conf.json frontendDist is "../out", confirming the dir.
const exportRoot = join(appRoot, "out");
const exportEntry = join(exportRoot, "index.html");

// PyInstaller --onefile exe for this project is on the order of tens of MB.
// Use a conservative lower bound so a truncated/failed build is caught without
// false positives on legitimate size drift.
const MIN_SIDECAR_BYTES = 1_000_000;

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

assert(existsSync(sidecarExePath), `Sidecar executable was not found: ${sidecarExePath}`);

const sidecarSize = statSync(sidecarExePath).size;
assert(
  sidecarSize > MIN_SIDECAR_BYTES,
  `Sidecar executable is unexpectedly small: ${sidecarSize} bytes (expected > ${MIN_SIDECAR_BYTES})`,
);

assert(existsSync(exportRoot), `Next.js export directory was not found: ${exportRoot}`);
assert(existsSync(exportEntry), `Next.js export entry was not found: ${exportEntry}`);

const exportEntryCount = readdirSync(exportRoot).length;
assert(exportEntryCount > 0, `Next.js export directory is empty: ${exportRoot}`);

console.log(
  JSON.stringify(
    {
      ok: true,
      sidecar: { name: sidecarExeName, bytes: sidecarSize },
      export: { root: exportRoot, entries: exportEntryCount },
    },
    null,
    2,
  ),
);

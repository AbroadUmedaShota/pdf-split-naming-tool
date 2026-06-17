import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const appRoot = join(scriptDir, "..");
const bundleRoot = join(appRoot, "src-tauri", "target", "release", "bundle");
const releaseAssetRoot = join(bundleRoot, "release-assets");
const packageJson = JSON.parse(readFileSync(join(appRoot, "package.json"), "utf-8"));

const version = packageJson.version;
const installerName = `pdf-organizer-desktop_${version}_x64-setup.exe`;
const signatureName = `${installerName}.sig`;
const manifestName = "latest.json";
const expectedFiles = new Set([installerName, signatureName, manifestName]);

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

function readText(filePath) {
  return readFileSync(filePath, "utf-8").trim();
}

const installerPath = join(releaseAssetRoot, installerName);
const signaturePath = join(releaseAssetRoot, signatureName);
const manifestPath = join(releaseAssetRoot, manifestName);

assert(existsSync(installerPath), `Release installer was not found: ${installerPath}`);
assert(existsSync(signaturePath), `Release signature was not found: ${signaturePath}`);
assert(existsSync(manifestPath), `Updater manifest was not found: ${manifestPath}`);

const installerSize = statSync(installerPath).size;
assert(installerSize > 1_000_000, `Release installer is unexpectedly small: ${installerSize} bytes`);

const signature = readText(signaturePath);
assert(signature.length > 0, "Release signature is empty");

const manifest = JSON.parse(readText(manifestPath));
const platform = manifest.platforms?.["windows-x86_64"];
assert(manifest.version === version, `Manifest version ${manifest.version} does not match package version ${version}`);
assert(platform, "Manifest does not contain windows-x86_64 platform data");
assert(platform.signature === signature, "Manifest signature does not match the generated .sig file");
assert(
  typeof platform.url === "string" && platform.url.endsWith(encodeURIComponent(installerName)),
  `Manifest URL does not point to ${installerName}`,
);

const staleAssets = readdirSync(releaseAssetRoot)
  .filter((name) => name.startsWith("pdf-organizer-desktop_") || name === manifestName)
  .filter((name) => !expectedFiles.has(name));
assert(staleAssets.length === 0, `Release asset directory contains stale assets: ${staleAssets.join(", ")}`);

console.log(
  JSON.stringify(
    {
      ok: true,
      version,
      releaseAssetRoot,
      files: [
        { name: installerName, bytes: installerSize },
        { name: signatureName, bytes: statSync(signaturePath).size },
        { name: manifestName, bytes: statSync(manifestPath).size },
      ],
    },
    null,
    2,
  ),
);

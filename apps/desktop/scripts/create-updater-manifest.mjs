import { copyFileSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const appRoot = join(scriptDir, "..");
const bundleRoot = join(appRoot, "src-tauri", "target", "release", "bundle");
const releaseAssetRoot = join(bundleRoot, "release-assets");
const packageJson = JSON.parse(readFileSync(join(appRoot, "package.json"), "utf-8"));
const releaseBaseUrl =
  process.env.PDF_ORGANIZER_RELEASE_BASE_URL ??
  "https://github.com/AbroadUmedaShota/pdf-split-naming-tool/releases/latest/download/";

function findUpdaterAsset() {
  const versionPattern = packageJson.version.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const candidates = [
    { dir: join(bundleRoot, "nsis"), pattern: new RegExp(`_${versionPattern}_x64-setup\\.exe$`) },
    { dir: join(bundleRoot, "msi"), pattern: new RegExp(`_${versionPattern}_x64_ja-JP\\.msi$`) }
  ];

  for (const candidate of candidates) {
    let files;
    try {
      files = readdirSync(candidate.dir, { withFileTypes: true });
    } catch {
      continue;
    }
    const asset = files
      .filter((entry) => entry.isFile())
      .map((entry) => entry.name)
      .find((name) => candidate.pattern.test(name) && files.some((entry) => entry.name === `${name}.sig`));
    if (asset) {
      return {
        assetName: asset,
        assetPath: join(candidate.dir, asset),
        signaturePath: join(candidate.dir, `${asset}.sig`)
      };
    }
  }

  throw new Error("Updater installer and .sig were not found. Run `npm run tauri build` first.");
}

function releaseAssetNameFor(sourceName) {
  const suffix = sourceName.endsWith(".msi") ? "_x64_ja-JP.msi" : "_x64-setup.exe";
  return `pdf-organizer-desktop_${packageJson.version}${suffix}`;
}

const { assetName, assetPath, signaturePath } = findUpdaterAsset();
const releaseAssetName = releaseAssetNameFor(assetName);
const releaseSignatureName = `${releaseAssetName}.sig`;
mkdirSync(releaseAssetRoot, { recursive: true });
copyFileSync(assetPath, join(releaseAssetRoot, releaseAssetName));
copyFileSync(signaturePath, join(releaseAssetRoot, releaseSignatureName));

const signature = readFileSync(signaturePath, "utf-8").trim();
const manifest = {
  version: packageJson.version,
  notes: `PDF整理ツール ${packageJson.version}`,
  pub_date: new Date().toISOString(),
  platforms: {
    "windows-x86_64": {
      signature,
      url: `${releaseBaseUrl}${encodeURIComponent(releaseAssetName)}`
    }
  }
};

const manifestPath = join(releaseAssetRoot, "latest.json");
writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`, "utf-8");
console.log(`Updater manifest: ${manifestPath}`);
console.log(`Updater asset: ${releaseAssetName}`);
console.log(`Updater signature: ${releaseSignatureName}`);

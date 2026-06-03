import { readFileSync, readdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const appRoot = join(scriptDir, "..");
const bundleRoot = join(appRoot, "src-tauri", "target", "release", "bundle");
const packageJson = JSON.parse(readFileSync(join(appRoot, "package.json"), "utf-8"));
const releaseBaseUrl =
  process.env.PDF_ORGANIZER_RELEASE_BASE_URL ??
  "https://github.com/AbroadUmedaShota/pdf-split-naming-tool/releases/latest/download/";

function findUpdaterAsset() {
  const candidates = [
    { dir: join(bundleRoot, "nsis"), pattern: /setup\.exe$/ },
    { dir: join(bundleRoot, "msi"), pattern: /\.msi$/ }
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

const { assetName, signaturePath } = findUpdaterAsset();
const signature = readFileSync(signaturePath, "utf-8").trim();
const manifest = {
  version: packageJson.version,
  notes: `PDF整理ツール ${packageJson.version}`,
  pub_date: new Date().toISOString(),
  platforms: {
    "windows-x86_64": {
      signature,
      url: `${releaseBaseUrl}${encodeURIComponent(assetName)}`
    }
  }
};

const manifestPath = join(bundleRoot, "latest.json");
writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`, "utf-8");
console.log(`Updater manifest: ${manifestPath}`);
console.log(`Updater asset: ${assetName}`);

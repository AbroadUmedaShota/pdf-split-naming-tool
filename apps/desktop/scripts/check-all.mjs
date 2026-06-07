import { spawnSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const desktopRoot = join(__dirname, "..");

const checks = [
  "check-preview-cache.mjs",
  "check-restore-state.mjs",
  "check-filename-policy.mjs",
  "check-output-state.mjs",
  "check-segment-state.mjs",
  "check-step-layout.mjs",
];

for (const check of checks) {
  const relativePath = join("scripts", check);
  console.log(`[test:desktop] running ${relativePath}`);

  const result = spawnSync(process.execPath, [join(__dirname, check)], {
    cwd: desktopRoot,
    stdio: "inherit",
  });

  if (result.error) {
    console.error(`[test:desktop] failed to start ${relativePath}: ${result.error.message}`);
    process.exit(1);
  }

  if (result.status !== 0) {
    if (result.signal) {
      console.error(`[test:desktop] ${relativePath} terminated by signal ${result.signal}`);
    } else {
      console.error(`[test:desktop] ${relativePath} failed with exit code ${result.status}`);
    }
    process.exit(result.status ?? 1);
  }
}

console.log(`[test:desktop] passed ${checks.length} checks`);

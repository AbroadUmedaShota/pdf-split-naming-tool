import { chromium, expect } from "@playwright/test";
import { spawn, spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import net from "node:net";

const oldVersion = process.env.PDF_ORGANIZER_UPDATER_OLD_VERSION ?? "0.1.3";
const newVersion = process.env.PDF_ORGANIZER_UPDATER_NEW_VERSION ?? "0.1.4";
const oldInstallerPath =
  process.env.PDF_ORGANIZER_UPDATER_OLD_INSTALLER_PATH ??
  resolve("src-tauri", "target", "release", "bundle", "nsis", `PDF整理ツール_${oldVersion}_x64-setup.exe`);
const appPath =
  process.env.PDF_ORGANIZER_INSTALLED_EXE ??
  join(process.env.LOCALAPPDATA ?? "", "PDF整理ツール", "pdf-organizer-desktop.exe");
const screenshotPath =
  process.env.PDF_ORGANIZER_INSTALLED_UPDATER_SCREENSHOT ??
  join(tmpdir(), `pdf-tool-installed-updater-smoke-${Date.now()}.png`);

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

function freePort() {
  return new Promise((resolvePort, reject) => {
    const server = net.createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      server.close(() => resolvePort(address.port));
    });
  });
}

async function sleep(ms) {
  return new Promise((resolveSleep) => setTimeout(resolveSleep, ms));
}

async function waitForCdp(port) {
  const deadline = Date.now() + 60_000;
  let lastError = null;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/json/version`);
      if (response.ok) {
        return;
      }
    } catch (error) {
      lastError = error;
    }
    await sleep(500);
  }
  throw new Error(`Timed out waiting for WebView2 CDP: ${lastError?.message ?? "no response"}`);
}

async function waitForProcessExit(child, timeoutMs) {
  if (!child || child.exitCode !== null || child.signalCode !== null) {
    return true;
  }
  return new Promise((resolveExit) => {
    const timer = setTimeout(() => resolveExit(false), timeoutMs);
    child.once("exit", () => {
      clearTimeout(timer);
      resolveExit(true);
    });
  });
}

async function terminateProcess(child) {
  if (!child || child.exitCode !== null || child.signalCode !== null) {
    return;
  }
  child.kill();
  if (await waitForProcessExit(child, 3_000)) {
    return;
  }
  spawnSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], { stdio: "ignore" });
}

async function stopInstalledApp() {
  spawnSync("taskkill", ["/IM", "pdf-organizer-desktop.exe", "/F"], { stdio: "ignore" });
  await sleep(3_000);
}

function installOldVersion() {
  assert(existsSync(oldInstallerPath), `Old installer was not found: ${oldInstallerPath}`);
  const result = spawnSync(oldInstallerPath, ["/S"], { stdio: "inherit" });
  assert(result.status === 0, `Old installer failed with exit code ${result.status}`);
  assert(existsSync(appPath), `Installed app was not found after install: ${appPath}`);
}

async function launchApp() {
  const port = await freePort();
  let child = null;
  let lastError = null;
  for (let attempt = 1; attempt <= 10; attempt += 1) {
    try {
      child = spawn(appPath, [], {
        env: {
          ...process.env,
          WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS: `--remote-debugging-port=${port}`,
        },
        stdio: "ignore",
      });
      break;
    } catch (error) {
      lastError = error;
      if (error?.code !== "EBUSY" || attempt === 10) {
        throw error;
      }
      await sleep(2_000);
    }
  }
  assert(child, `Could not launch app: ${lastError?.message ?? "unknown error"}`);
  await waitForCdp(port);
  const browser = await chromium.connectOverCDP(`http://127.0.0.1:${port}`);
  const context = browser.contexts()[0];
  const page = context.pages()[0] ?? (await context.waitForEvent("page", { timeout: 10_000 }));
  await page.waitForLoadState("domcontentloaded");
  return { browser, child, page };
}

async function main() {
  await stopInstalledApp();
  installOldVersion();

  let session = await launchApp();
  try {
    await expect(session.page.locator(".update-copy small")).toContainText(oldVersion, { timeout: 30_000 });
    await session.page.getByRole("button", { name: /更新確認/ }).click();
    await expect(session.page.locator(".update-copy strong")).toHaveText(`新しいバージョン ${newVersion} があります。`, {
      timeout: 60_000,
    });
    await session.page.getByRole("button", { name: /インストール/ }).click();
    await expect(session.page.locator(".update-copy strong")).toContainText(
      /更新をダウンロードしています。|更新をインストールしました。/,
      { timeout: 60_000 },
    );
    await waitForProcessExit(session.child, 300_000);
  } finally {
    try {
      await session.browser.close();
    } catch {
      // The updater may close the WebView before Playwright disconnects.
    }
    await terminateProcess(session.child);
  }

  await stopInstalledApp();
  session = await launchApp();
  try {
    await expect(session.page.locator(".update-copy small")).toContainText(newVersion, { timeout: 30_000 });
    await session.page.getByRole("button", { name: /更新確認/ }).click();
    await expect(session.page.locator(".update-copy strong")).toHaveText("最新版です。", { timeout: 60_000 });
    await session.page.screenshot({ path: screenshotPath, fullPage: true });
    console.log(
      JSON.stringify(
        {
          ok: true,
          appPath,
          from: oldVersion,
          to: newVersion,
          latestMessage: "最新版です。",
          screenshotPath,
        },
        null,
        2,
      ),
    );
  } finally {
    try {
      await session.browser.close();
    } catch {
      // best effort cleanup
    }
    await terminateProcess(session.child);
  }
}

await main();

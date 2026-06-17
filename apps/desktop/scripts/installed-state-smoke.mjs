import { chromium, expect } from "@playwright/test";
import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import net from "node:net";

const appPath =
  process.env.PDF_ORGANIZER_INSTALLED_EXE ??
  join(process.env.LOCALAPPDATA ?? "", "PDF整理ツール", "pdf-organizer-desktop.exe");
const keepTemp = process.env.PDF_ORGANIZER_KEEP_INSTALLED_STATE_TMP === "1";
const screenshotPath =
  process.env.PDF_ORGANIZER_INSTALLED_STATE_SCREENSHOT ??
  join(tmpdir(), `pdf-tool-installed-state-smoke-${Date.now()}.png`);

function buildPdf(objects) {
  let body = "%PDF-1.4\n";
  const offsets = [0];
  for (const object of objects) {
    offsets.push(Buffer.byteLength(body, "latin1"));
    body += `${object.id} 0 obj\n${object.body}\nendobj\n`;
  }

  const xrefOffset = Buffer.byteLength(body, "latin1");
  body += `xref\n0 ${objects.length + 1}\n`;
  body += "0000000000 65535 f \n";
  for (const offset of offsets.slice(1)) {
    body += `${String(offset).padStart(10, "0")} 00000 n \n`;
  }
  body += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF\n`;
  return Buffer.from(body, "latin1");
}

function streamObject(text) {
  const content = `BT /F1 18 Tf 50 220 Td (${text}) Tj ET\n`;
  return `<< /Length ${Buffer.byteLength(content, "latin1")} >>\nstream\n${content}endstream`;
}

function writeSamplePdf(pdfPath) {
  writeFileSync(
    pdfPath,
    buildPdf([
      { id: 1, body: "<< /Type /Catalog /Pages 2 0 R >>" },
      { id: 2, body: "<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>" },
      {
        id: 3,
        body:
          "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] " +
          "/Resources << /Font << /F1 5 0 R >> >> /Contents 6 0 R >>",
      },
      {
        id: 4,
        body:
          "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] " +
          "/Resources << /Font << /F1 5 0 R >> >> /Contents 7 0 R >>",
      },
      { id: 5, body: "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>" },
      { id: 6, body: streamObject("Installed state smoke page 1") },
      { id: 7, body: streamObject("Installed state smoke page 2") },
    ]),
  );
}

async function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      server.close(() => resolve(address.port));
    });
  });
}

async function waitForCdp(port) {
  const deadline = Date.now() + 30_000;
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
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`Timed out waiting for WebView2 CDP: ${lastError?.message ?? "no response"}`);
}

async function waitForProcessExit(child, timeoutMs) {
  if (child.exitCode !== null || child.signalCode !== null) {
    return true;
  }
  return new Promise((resolve) => {
    const timer = setTimeout(() => resolve(false), timeoutMs);
    child.once("exit", () => {
      clearTimeout(timer);
      resolve(true);
    });
  });
}

async function terminateProcess(child) {
  if (!child || child.exitCode !== null || child.signalCode !== null) {
    return;
  }
  child.kill();
  if (await waitForProcessExit(child, 2_000)) {
    return;
  }
  spawnSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], { stdio: "ignore" });
}

async function launchApp({ outputDir, pdfPath, route, workDir }) {
  const port = await freePort();
  const child = spawn(appPath, [], {
    env: {
      ...process.env,
      PDF_ORGANIZER_SIDECAR_TIMEOUT_MS: "120000",
      PDF_ORGANIZER_WORK_DIR: workDir,
      WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS: `--remote-debugging-port=${port}`,
    },
    stdio: "ignore",
  });

  await waitForCdp(port);
  const browser = await chromium.connectOverCDP(`http://127.0.0.1:${port}`);
  const context = browser.contexts()[0];
  const page = context.pages()[0] ?? (await context.waitForEvent("page", { timeout: 5_000 }));
  const pageErrors = [];
  const consoleMessages = [];

  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("console", (message) => {
    if (["error", "warning"].includes(message.type())) {
      consoleMessages.push(`${message.type()}: ${message.text()}`);
    }
  });

  await page.addInitScript(
    ({ outputDir, pdfPath }) => {
      window.__PDF_TOOL_E2E__ = {
        async openDialog(options) {
          return options?.directory ? outputDir : [pdfPath];
        },
      };
    },
    { outputDir, pdfPath },
  );

  await page.goto(`http://tauri.localhost/?e2e=${route}`, { waitUntil: "domcontentloaded" });
  await expect(page).toHaveTitle("PDF整理ツール", { timeout: 30_000 });
  await expect(page.getByRole("heading", { name: "PDF整理ツール" })).toBeVisible({ timeout: 30_000 });

  return { browser, child, consoleMessages, page, pageErrors };
}

async function closeLaunch(session) {
  await session.browser.close().catch(() => {});
  await terminateProcess(session.child);
}

async function fillSegment(page, index, { binder, box, seq }) {
  await page.locator(".mini-row").nth(index).click();
  await page.locator('input[name="box_no"]').fill(box);
  await page.locator('input[name="binder_no"]').fill(binder);
  await page.locator('input[name="seq"]').fill(seq);
}

async function expectSegment(page, index, { binder, box, seq }) {
  await page.locator(".mini-row").nth(index).click();
  await expect(page.locator('input[name="box_no"]')).toHaveValue(box);
  await expect(page.locator('input[name="binder_no"]')).toHaveValue(binder);
  await expect(page.locator('input[name="seq"]')).toHaveValue(seq);
}

async function main() {
  if (!existsSync(appPath)) {
    throw new Error(`Installed app was not found: ${appPath}`);
  }

  const tempRoot = mkdtempSync(join(tmpdir(), "pdf-tool-installed-state-"));
  const pdfPath = join(tempRoot, "State Smoke 日本語 path.pdf");
  const outputDir = join(tempRoot, "output folder");
  const workDir = join(tempRoot, "work");
  mkdirSync(outputDir, { recursive: true });
  mkdirSync(workDir, { recursive: true });
  writeSamplePdf(pdfPath);

  let saveSession = null;
  let restoreSession = null;
  try {
    saveSession = await launchApp({ outputDir, pdfPath, route: "installed-state-save", workDir });
    const savePage = saveSession.page;

    await savePage.getByRole("button", { name: "PDFを選択" }).first().click();
    await expect(savePage.getByText("State Smoke 日本語 path.pdf").first()).toBeVisible({ timeout: 120_000 });
    await expect(savePage.getByText("2ページ").first()).toBeVisible({ timeout: 120_000 });
    await savePage.getByRole("button", { name: "出力フォルダ" }).click();
    await expect(savePage.locator('[role="status"]')).toContainText("出力フォルダを設定しました。", { timeout: 30_000 });

    await savePage.getByRole("button", { name: "分割へ進む" }).click();
    await expect(savePage.locator('[data-testid="step-split"][aria-current="step"]')).toBeAttached({ timeout: 30_000 });
    await savePage.getByRole("button", { name: "次ページ" }).click();
    await expect(savePage.getByRole("spinbutton", { name: "ページ番号" })).toHaveValue("2", { timeout: 120_000 });
    await savePage.getByRole("button", { name: "現在ページの前で分割" }).click();
    await expect(savePage.locator('[role="status"]')).toContainText("2ページの前に分割を追加しました。", { timeout: 30_000 });

    await savePage.getByRole("button", { name: "入力へ進む" }).click();
    await expect(savePage.locator('[data-testid="step-input"][aria-current="step"]')).toBeAttached({ timeout: 30_000 });
    await expect(savePage.locator(".mini-row")).toHaveCount(2, { timeout: 30_000 });
    await fillSegment(savePage, 0, { binder: "8", box: "7", seq: "9" });
    await fillSegment(savePage, 1, { binder: "8", box: "7", seq: "10" });
    await expect(savePage.getByLabel("入力完了条件")).toContainText("未入力0件", { timeout: 30_000 });

    await savePage.locator('[data-testid="step-import"]').click();
    await expect(savePage.locator('[data-testid="step-import"][aria-current="step"]')).toBeAttached({ timeout: 30_000 });
    await savePage.getByRole("button", { name: "状態を保存" }).click();
    await expect(savePage.locator('[role="status"]')).toContainText("状態を保存しました。", { timeout: 120_000 });
    expect(saveSession.pageErrors, "Installed app state-save should not produce page errors").toEqual([]);
    expect(saveSession.consoleMessages, "Installed app state-save should not produce console warnings/errors").toEqual([]);

    await closeLaunch(saveSession);
    saveSession = null;

    restoreSession = await launchApp({ outputDir, pdfPath, route: "installed-state-restore", workDir });
    const restorePage = restoreSession.page;

    await restorePage.getByRole("button", { name: "状態を復元" }).click();
    await expect(restorePage.locator('[role="status"]')).toContainText("状態を復元しました。", { timeout: 120_000 });
    await expect(restorePage.getByText("State Smoke 日本語 path.pdf").first()).toBeVisible({ timeout: 120_000 });
    await expect(restorePage.getByText("2ページ").first()).toBeVisible({ timeout: 120_000 });
    await expect(restorePage.getByText(outputDir).first()).toBeVisible({ timeout: 30_000 });

    await restorePage.getByRole("button", { name: "分割へ進む" }).click();
    await expect(restorePage.locator('[data-testid="step-split"][aria-current="step"]')).toBeAttached({ timeout: 30_000 });
    await restorePage.getByRole("button", { name: "入力へ進む" }).click();
    await expect(restorePage.locator('[data-testid="step-input"][aria-current="step"]')).toBeAttached({ timeout: 30_000 });
    await expect(restorePage.locator(".mini-row")).toHaveCount(2, { timeout: 30_000 });
    await expectSegment(restorePage, 0, { binder: "8", box: "7", seq: "9" });
    await expectSegment(restorePage, 1, { binder: "8", box: "7", seq: "10" });
    await restorePage.screenshot({ fullPage: false, path: screenshotPath, timeout: 120_000 });

    expect(restoreSession.pageErrors, "Installed app state-restore should not produce page errors").toEqual([]);
    expect(restoreSession.consoleMessages, "Installed app state-restore should not produce console warnings/errors").toEqual([]);

    console.log(
      JSON.stringify(
        {
          ok: true,
          appPath,
          outputDir: keepTemp ? outputDir : undefined,
          pdfPath,
          screenshotPath,
          tempRoot: keepTemp ? tempRoot : undefined,
          workDir: keepTemp ? workDir : undefined,
        },
        null,
        2,
      ),
    );
  } finally {
    if (saveSession) {
      await closeLaunch(saveSession);
    }
    if (restoreSession) {
      await closeLaunch(restoreSession);
    }
    if (!keepTemp) {
      rmSync(tempRoot, { recursive: true, force: true });
    }
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});

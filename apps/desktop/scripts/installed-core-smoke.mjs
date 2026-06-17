import { chromium, expect } from "@playwright/test";
import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, join, resolve } from "node:path";
import net from "node:net";

const appPath =
  process.env.PDF_ORGANIZER_INSTALLED_EXE ??
  join(process.env.LOCALAPPDATA ?? "", "PDF整理ツール", "pdf-organizer-desktop.exe");
const keepTemp = process.env.PDF_ORGANIZER_KEEP_INSTALLED_CORE_TMP === "1";
const screenshotPath =
  process.env.PDF_ORGANIZER_INSTALLED_CORE_SCREENSHOT ??
  join(tmpdir(), `pdf-tool-installed-core-smoke-${Date.now()}.png`);
const providedPdfPath = process.env.PDF_ORGANIZER_INSTALLED_CORE_PDF_PATH?.trim();
const expectedPageCount = process.env.PDF_ORGANIZER_INSTALLED_CORE_EXPECTED_PAGES?.trim();
const preexistingOutputMode = process.env.PDF_ORGANIZER_INSTALLED_CORE_PREEXISTING_OUTPUT === "1";

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
      { id: 6, body: streamObject("Installed core smoke page 1") },
      { id: 7, body: streamObject("Installed core smoke page 2") },
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

async function main() {
  if (!existsSync(appPath)) {
    throw new Error(`Installed app was not found: ${appPath}`);
  }

  const tempRoot = mkdtempSync(join(tmpdir(), "pdf-tool-installed-core-"));
  const pdfPath = providedPdfPath ? resolve(providedPdfPath) : join(tempRoot, "Core Smoke 日本語 path.pdf");
  const pdfName = basename(pdfPath);
  const outputDir = join(tempRoot, "output folder");
  mkdirSync(outputDir, { recursive: true });
  const preexistingOutputPath = join(outputDir, "01_01_001.pdf");
  if (providedPdfPath) {
    if (!existsSync(pdfPath)) {
      throw new Error(`Provided PDF was not found: ${pdfPath}`);
    }
  } else {
    writeSamplePdf(pdfPath);
  }
  if (preexistingOutputMode) {
    writeFileSync(preexistingOutputPath, "existing output must not be overwritten");
  }

  const port = await freePort();
  let browser = null;
  const child = spawn(appPath, [], {
    env: {
      ...process.env,
      PDF_ORGANIZER_SIDECAR_TIMEOUT_MS: "120000",
      WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS: `--remote-debugging-port=${port}`,
    },
    stdio: "ignore",
  });

  try {
    await waitForCdp(port);
    browser = await chromium.connectOverCDP(`http://127.0.0.1:${port}`);
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

    await page.goto("http://tauri.localhost/?e2e=installed-core", { waitUntil: "domcontentloaded" });
    await expect(page).toHaveTitle("PDF整理ツール", { timeout: 30_000 });
    await expect(page.getByRole("heading", { name: "PDF整理ツール" })).toBeVisible({ timeout: 30_000 });

    await page.getByRole("button", { name: "PDFを選択" }).first().click();
    await expect(page.getByText(pdfName).first()).toBeVisible({ timeout: 120_000 });
    const pageCountText = expectedPageCount || (providedPdfPath ? null : "2");
    if (pageCountText) {
      await expect(page.getByText(`${pageCountText}ページ`).first()).toBeVisible({ timeout: 120_000 });
    } else {
      await expect(page.locator(".queue-row").first()).toContainText(/\d+ページ/, { timeout: 120_000 });
    }
    await expect(page.locator('[role="status"]')).toContainText("1件のPDFを読み込みました。", { timeout: 120_000 });

    await page.getByRole("button", { name: "出力フォルダ" }).click();
    await expect(page.locator('[role="status"]')).toContainText("出力フォルダを設定しました。", { timeout: 30_000 });

    await page.getByRole("button", { name: "分割へ進む" }).click();
    await expect(page.locator('[data-testid="step-split"][aria-current="step"]')).toBeAttached({ timeout: 30_000 });
    await page.getByRole("button", { name: "次ページ" }).click();
    await expect(page.getByRole("spinbutton", { name: "ページ番号" })).toHaveValue("2", { timeout: 120_000 });
    await page.getByRole("button", { name: "現在ページの前で分割" }).click();
    await expect(page.locator('[role="status"]')).toContainText("2ページの前に分割を追加しました。", { timeout: 30_000 });
    await page.getByRole("button", { name: "入力へ進む" }).click();

    await expect(page.locator('[data-testid="step-input"][aria-current="step"]')).toBeAttached({ timeout: 30_000 });
    await expect(page.locator(".mini-row")).toHaveCount(2, { timeout: 30_000 });
    await page.locator(".mini-row").nth(0).click();
    await page.locator('input[name="box_no"]').fill("1");
    await page.locator('input[name="binder_no"]').fill("1");
    await page.locator('input[name="seq"]').fill("1");
    await page.locator(".mini-row").nth(1).click();
    await page.locator('input[name="box_no"]').fill("1");
    await page.locator('input[name="binder_no"]').fill("1");
    await page.locator('input[name="seq"]').fill("2");
    await expect(page.getByLabel("入力完了条件")).toContainText("未入力0件", { timeout: 30_000 });
    await page.getByRole("button", { name: "出力前チェック" }).last().click();

    await expect(page.locator('[data-testid="step-output"][aria-current="step"]')).toBeAttached({ timeout: 120_000 });
    if (preexistingOutputMode) {
      await expect(page.locator('[role="status"]')).toContainText("修正が必要な項目があります。", { timeout: 120_000 });
      await expect(page.getByText("既存あり（要対処）")).toBeVisible({ timeout: 30_000 });
      await expect(page.getByText("同名ファイルが既存です。出力先を変更するか既存ファイルを削除してください")).toBeVisible({
        timeout: 30_000,
      });
      await expect(page.getByRole("button", { name: "出力実行" })).toBeDisabled();
      await page.screenshot({ fullPage: false, path: screenshotPath });

      const outputs = readdirSync(outputDir).filter((name) => name.toLowerCase().endsWith(".pdf")).sort();
      expect(outputs, "Existing-output smoke should not create additional PDFs").toEqual(["01_01_001.pdf"]);
      expect(pageErrors, "Installed app existing-output smoke should not produce page errors").toEqual([]);
      expect(consoleMessages, "Installed app existing-output smoke should not produce console warnings/errors").toEqual([]);

      console.log(
        JSON.stringify(
          {
            ok: true,
            appPath,
            mode: "preexisting-output",
            pdfPath,
            preexistingOutputPath,
            outputDir: keepTemp ? outputDir : undefined,
            outputs,
            screenshotPath,
            tempRoot: keepTemp ? tempRoot : undefined,
          },
          null,
          2,
        ),
      );
      return;
    }

    await expect(page.locator('[role="status"]')).toContainText("出力できます。", { timeout: 120_000 });
    await page.getByRole("button", { name: "出力実行" }).click();
    await expect(page.locator('[role="status"]')).toContainText("出力が完了しました。", { timeout: 120_000 });
    await expect(page.getByText("作成 2件 / 失敗 0件")).toBeVisible({ timeout: 30_000 });
    await page.screenshot({ fullPage: false, path: screenshotPath });

    const outputs = readdirSync(outputDir).filter((name) => name.toLowerCase().endsWith(".pdf")).sort();
    expect(outputs, "Core smoke should create two split PDFs").toEqual(["01_01_001.pdf", "01_01_002.pdf"]);
    expect(pageErrors, "Installed app core smoke should not produce page errors").toEqual([]);
    expect(consoleMessages, "Installed app core smoke should not produce console warnings/errors").toEqual([]);

    console.log(
      JSON.stringify(
        {
          ok: true,
          appPath,
          pdfPath,
          outputDir: keepTemp ? outputDir : undefined,
          outputs,
          screenshotPath,
          tempRoot: keepTemp ? tempRoot : undefined,
        },
        null,
        2,
      ),
    );
  } finally {
    if (browser) {
      await browser.close().catch(() => {});
    }
    await terminateProcess(child);
    if (!keepTemp) {
      rmSync(tempRoot, { recursive: true, force: true });
    }
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});

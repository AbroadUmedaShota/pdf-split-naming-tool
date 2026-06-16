import { chromium, expect } from "@playwright/test";
import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import net from "node:net";

const appPath =
  process.env.PDF_ORGANIZER_INSTALLED_EXE ??
  join(process.env.LOCALAPPDATA ?? "", "PDF整理ツール", "pdf-organizer-desktop.exe");
const keepTemp = process.env.PDF_ORGANIZER_KEEP_INSTALLED_SMOKE_TMP === "1";
const screenshotPath =
  process.env.PDF_ORGANIZER_INSTALLED_SMOKE_SCREENSHOT ??
  join(tmpdir(), `pdf-tool-installed-step1-smoke-${Date.now()}.png`);
const passwordErrorScreenshotPath = screenshotPath.replace(/(\.[^.\\/]+)?$/, "-password-error.png");
const encryptedPdfBase64 =
  "JVBERi0xLjcKJcK1wrYKCjEgMCBvYmoKPDwvVHlwZS9DYXRhbG9nL1BhZ2VzIDIgMCBSPj4KZW5kb2JqCgoyIDAgb2JqCjw8L1R5cGUvUGFnZXMvQ291bnQgMS9LaWRzWzQgMCBSXT4+CmVuZG9iagoKMyAwIG9iago8PC9Gb250PDwvaGVsdiA1IDAgUj4+Pj4KZW5kb2JqCgo0IDAgb2JqCjw8L1R5cGUvUGFnZS9NZWRpYUJveFswIDAgMzAwIDMwMF0vUm90YXRlIDAvUmVzb3VyY2VzIDMgMCBSL1BhcmVudCAyIDAgUi9Db250ZW50c1s2IDAgUl0+PgplbmRvYmoKCjUgMCBvYmoKPDwvVHlwZS9Gb250L1N1YnR5cGUvVHlwZTEvQmFzZUZvbnQvSGVsdmV0aWNhL0VuY29kaW5nL1dpbkFuc2lFbmNvZGluZz4+CmVuZG9iagoKNiAwIG9iago8PC9MZW5ndGggMTEyL0ZpbHRlci9GbGF0ZURlY29kZT4+CnN0cmVhbQqUCwKau6cGbVbwGdKfJoTUzIoya+Hc0PuP9XMwJPF6MkQ8qotB5mocKnIjAuKzlnlOrvDOyN/lLeN79E9Ms2TRSQv7ZCYRkAVLAXz3kcaBDbuYWYMaK4J5BIjAKEr1CJ4FWAx52Qz9KMMfLxulZnh5CmVuZHN0cmVhbQplbmRvYmoKCnhyZWYKMCA3CjAwMDAwMDAwMDAgNjU1MzUgZiAKMDAwMDAwMDAxNiAwMDAwMCBuIAowMDAwMDAwMDYyIDAwMDAwIG4gCjAwMDAwMDAxMTQgMDAwMDAgbiAKMDAwMDAwMDE1NSAwMDAwMCBuIAowMDAwMDAwMjYyIDAwMDAwIG4gCjAwMDAwMDAzNTEgMDAwMDAgbiAKCnRyYWlsZXIKPDwvU2l6ZSA3L1Jvb3QgMSAwIFIvSURbPDVEQzJCQTQ2QzNBNjM4MDRDMzlEQzM5QzFBNUQ3M0MzPjw1M0RBRTRDQTk5MkI3RDBCN0E4NzY2QkExQTRCQ0VEQz5dL0VuY3J5cHQ8PC9GaWx0ZXIvU3RhbmRhcmQvUiA2L1YgNS9MZW5ndGggMjU2L1AgLTQvRW5jcnlwdE1ldGFkYXRhIHRydWUvU3RtRi9TdGRDRi9TdHJGL1N0ZENGL0NGPDwvU3RkQ0Y8PC9BdXRoRXZlbnQvRG9jT3Blbi9DRk0vQUVTVjMvTGVuZ3RoIDMyPj4+Pi9PPDEyRDkxMTcxQUEwNkNFNkU1MDNDQThFRDk5ODk3OTBFQjIyOTk2RDgxQjAwQkExRTM1RDBBQjFFRTdBREVDQUJERDYwQTM2NTlDNjVCN0QzQTVGRTY0NUI3N0Q4QzNBND4vVTwzQjIwQTg1NTlDNzU0NjcwNkJGODUzQTAxMkYxMDQxNjNBODlGREQ2RkIxMEEyMzIzMDUyMzkzOTMyMEU0ODU5QjlBODg3M0Y1MjNGMUI4NTdBNjU4RTFGRUE0MjkwNUI+L09FPEFGQzNDMTNCOTI5MDQ0MTM2OTExRUE1MzBBM0VEOTY3MDc4M0Q0QTZCRDVDMjBGMTlFNUQwMTVGRkI0QUM3Qjg+L1VFPDk4OUJENEZENUM3QUQxNjJFQ0UzN0NCMThBNDNBNDk5Q0VDN0Q3MUE3RkEwNEU3M0NCQkQ4MDdBN0U2RDZEQjc+L1Blcm1zPDUzOUZFQUY4Njc5MTdCMkFEMzcwNjU2M0U1MUM5NTE1Pj4+Pj4Kc3RhcnR4cmVmCjUzMgolJUVPRgo=";

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
      { id: 6, body: streamObject("STEP1 page 1") },
      { id: 7, body: streamObject("STEP1 page 2") },
    ]),
  );
}

function writeEncryptedPdf(pdfPath) {
  writeFileSync(pdfPath, Buffer.from(encryptedPdfBase64, "base64"));
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

  const tempRoot = mkdtempSync(join(tmpdir(), "pdf-tool-installed-step1-"));
  const pdfPath = join(tempRoot, "STEP1 日本語 path smoke.pdf");
  const encryptedPdfPath = join(tempRoot, "STEP1 password protected.pdf");
  const outputDir = join(tempRoot, "output folder");
  mkdirSync(outputDir, { recursive: true });
  writeSamplePdf(pdfPath);
  writeEncryptedPdf(encryptedPdfPath);

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
      ({ encryptedPdfPath, outputDir, pdfPath }) => {
        const pdfOpenResults = [[encryptedPdfPath], [encryptedPdfPath, pdfPath]];
        window.__PDF_TOOL_E2E__ = {
          async openDialog(options) {
            if (options?.directory) {
              return outputDir;
            }
            return pdfOpenResults.shift() ?? [pdfPath];
          },
        };
      },
      { encryptedPdfPath, outputDir, pdfPath },
    );

    await page.goto("http://tauri.localhost/?e2e=installed", { waitUntil: "domcontentloaded" });
    await expect(page).toHaveTitle("PDF整理ツール", { timeout: 30_000 });
    await expect(page.getByRole("heading", { name: "PDF整理ツール" })).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText("PDFが未選択です")).toBeVisible();

    await page.getByRole("button", { name: "PDFを選択" }).first().click();
    await expect(page.locator('[role="status"]')).toContainText("PDF取込エラー", { timeout: 120_000 });
    await expect(page.locator('[role="status"]')).toContainText("パスワード付きPDFには対応していません", { timeout: 120_000 });
    await expect(page.locator('[role="status"]')).not.toContainText("Error:");
    await expect(page.locator(".queue-row")).toHaveCount(0);
    await expect(page.getByText("PDFが未選択です")).toBeVisible();
    await expect(page.getByRole("button", { name: "分割へ進む" })).toBeDisabled();
    await page.screenshot({ fullPage: false, path: passwordErrorScreenshotPath });

    await page.getByRole("button", { name: "PDFを選択" }).first().click();
    await expect(page.getByText("STEP1 日本語 path smoke.pdf").first()).toBeVisible({ timeout: 120_000 });
    await expect(page.getByText("2ページ").first()).toBeVisible({ timeout: 120_000 });
    await expect(page.locator(".queue-row")).toHaveCount(1);
    await expect(page.locator('[role="status"]')).toContainText("1件のPDFを読み込みました。", { timeout: 120_000 });
    await expect(page.locator('[role="status"]')).toContainText("1件は読み込めませんでした", { timeout: 120_000 });
    await expect(page.locator('[role="status"]')).not.toContainText("Error:");

    await page.getByRole("button", { name: "出力フォルダ" }).click();
    const nextButton = page.getByRole("button", { name: "分割へ進む" });
    await expect(nextButton).toBeEnabled({ timeout: 30_000 });
    await nextButton.click();
    await expect(page.locator('[data-testid="step-split"][aria-current="step"]')).toBeAttached({ timeout: 30_000 });
    await page.screenshot({ fullPage: false, path: screenshotPath });

    expect(pageErrors, "Installed app STEP1 smoke should not produce page errors").toEqual([]);
    expect(consoleMessages, "Installed app STEP1 smoke should not produce console warnings/errors").toEqual([]);

    console.log(
      JSON.stringify(
        {
          ok: true,
          appPath,
          passwordErrorScreenshotPath,
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

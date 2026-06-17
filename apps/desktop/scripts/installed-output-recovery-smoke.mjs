import { chromium, expect } from "@playwright/test";
import { spawn, spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, join } from "node:path";
import net from "node:net";

const appPath =
  process.env.PDF_ORGANIZER_INSTALLED_EXE ??
  join(process.env.LOCALAPPDATA ?? "", "PDF整理ツール", "pdf-organizer-desktop.exe");
const keepTemp = process.env.PDF_ORGANIZER_KEEP_INSTALLED_OUTPUT_RECOVERY_TMP === "1";
const screenshotPath =
  process.env.PDF_ORGANIZER_INSTALLED_OUTPUT_RECOVERY_SCREENSHOT ??
  join(tmpdir(), `pdf-tool-installed-output-recovery-smoke-${Date.now()}.png`);

async function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
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
    await sleep(500);
  }
  throw new Error(`Timed out waiting for WebView2 CDP: ${lastError?.message ?? "no response"}`);
}

async function gotoApp(page, url) {
  let lastError = null;
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    try {
      await page.goto(url, { waitUntil: "domcontentloaded" });
      await page.waitForFunction(() => new URL(window.location.href).searchParams.has("e2e"), null, { timeout: 5_000 });
      return;
    } catch (error) {
      lastError = error;
      if ((!String(error).includes("ERR_ABORTED") && !String(error).includes("Timeout")) || attempt === 3) {
        throw error;
      }
      await sleep(1_000);
    }
  }
  throw lastError;
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
  if (await waitForProcessExit(child, 2_000)) {
    return;
  }
  spawnSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], { stdio: "ignore" });
}

async function stopInstalledApp() {
  spawnSync("taskkill", ["/IM", "pdf-organizer-desktop.exe", "/F"], { stdio: "ignore" });
  await sleep(5_000);
}

function runExplorerProbe(outputDir, mode) {
  const ps = `
$target = [System.IO.Path]::GetFullPath($env:PDF_TOOL_TARGET).TrimEnd('\\')
$shell = New-Object -ComObject Shell.Application
$found = $false
foreach ($window in @($shell.Windows())) {
  try {
    $location = [System.IO.Path]::GetFullPath($window.Document.Folder.Self.Path).TrimEnd('\\')
    if ($location -ieq $target) {
      $found = $true
      if ($env:PDF_TOOL_EXPLORER_MODE -eq 'close') { $window.Quit() }
    }
  } catch {
  }
}
if ($found) { exit 0 }
exit 1
`;
  return spawnSync("powershell", ["-NoProfile", "-Command", ps], {
    encoding: "utf8",
    env: {
      ...process.env,
      PDF_TOOL_EXPLORER_MODE: mode,
      PDF_TOOL_TARGET: outputDir,
    },
  });
}

async function waitForExplorerFolder(outputDir) {
  const deadline = Date.now() + 15_000;
  let lastResult = null;
  while (Date.now() < deadline) {
    lastResult = runExplorerProbe(outputDir, "find");
    if (lastResult.status === 0) {
      return;
    }
    await sleep(500);
  }
  throw new Error(
    `Timed out waiting for Explorer to open ${outputDir}. stdout=${lastResult?.stdout ?? ""} stderr=${lastResult?.stderr ?? ""}`,
  );
}

function closeExplorerFolder(outputDir) {
  runExplorerProbe(outputDir, "close");
}

function pngDataUrl() {
  return "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgwJ/luzTmgAAAABJRU5ErkJggg==";
}

function writeMinimalPdf(pdfPath) {
  writeFileSync(
    pdfPath,
    "%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [] /Count 0 >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n",
  );
}

async function main() {
  await stopInstalledApp();

  const tempRoot = mkdtempSync(join(tmpdir(), "pdf-tool-installed-output-recovery-"));
  const outputDir = join(tempRoot, "Output Recovery 日本語 folder");
  const pdfPath = join(tempRoot, "Output Recovery 日本語 path.pdf");
  mkdirSync(outputDir, { recursive: true });
  writeMinimalPdf(pdfPath);

  const port = await freePort();
  let browser = null;
  const child = spawn(appPath, [], {
    env: {
      ...process.env,
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
      ({ outputDir, pdfPath, previewDataUrl }) => {
        window.__PDF_TOOL_E2E__ = {
          async openDialog(options) {
            return options?.directory ? outputDir : [pdfPath];
          },
          async invokeSidecar(request) {
            const command = request.command;
            if (command === "pdf_info") {
              return { ok: true, command, pdf_path: request.pdf_path, page_count: 3, naming_template: "{box}_{binder}_{seq}.pdf" };
            }
            if (command === "page_preview" || command === "page_thumbnail") {
              return {
                ok: true,
                command,
                pdf_path: request.pdf_path,
                page_no: request.page_no,
                page_count: 3,
                image_data_url: previewDataUrl,
              };
            }
            if (command === "page_text") {
              return { ok: true, command, pdf_path: request.pdf_path, page_no: request.page_no, page_count: 3, text: "", has_text: false };
            }
            if (command === "preflight") {
              return {
                ok: true,
                command,
                can_run: true,
                output_dir: request.output_dir,
                messages: [],
                checks: request.segments.map((segment) => outputItem(request.output_dir, segment)),
              };
            }
            if (command === "export") {
              window.__PDF_TOOL_EXPORT_CALLS__ = (window.__PDF_TOOL_EXPORT_CALLS__ ?? 0) + 1;
              const items = request.segments.map((segment) => outputItem(request.output_dir, segment));
              if (window.__PDF_TOOL_EXPORT_CALLS__ === 1 && items.length === 3) {
                items[0] = { ...items[0], status: "created", sha256: "created-1" };
                items[1] = {
                  ...items[1],
                  status: "failed",
                  error: "simulated locked file",
                  error_type: "PermissionError",
                };
                items[2] = { ...items[2], status: "created", sha256: "created-3" };
                return {
                  ok: false,
                  command,
                  output_dir: request.output_dir,
                  summary: { created: 2, failed: 1 },
                  items,
                  messages: ["export_incomplete"],
                };
              }
              return {
                ok: true,
                command,
                output_dir: request.output_dir,
                summary: { created: items.length, failed: 0 },
                items: items.map((item, index) => ({ ...item, status: "created", sha256: `retry-${index}` })),
                messages: [],
              };
            }
            return { ok: false, command, error: `Unexpected command ${command}`, error_type: "UnexpectedCommand" };

            function outputItem(outputRoot, segment) {
              const metadata = segment.metadata ?? {};
              const box = String(metadata.box_no ?? "1").padStart(2, "0");
              const binder = String(metadata.binder_no ?? "1").padStart(2, "0");
              const seq = String(metadata.seq ?? "1").padStart(3, "0");
              const filename = `${box}_${binder}_${seq}.pdf`;
              const outputPath = `${outputRoot}\\${filename}`;
              return {
                ok: true,
                filename,
                output_path: outputPath,
                messages: [],
                requested_filename: filename,
                requested_path: outputPath,
                existing_path: "",
                has_existing_output: false,
                metadata,
                pages: segment.start_page === segment.end_page ? String(segment.start_page) : `${segment.start_page}-${segment.end_page}`,
                pdf_path: segment.pdf_path,
              };
            }
          },
        };
      },
      { outputDir, pdfPath, previewDataUrl: pngDataUrl() },
    );

    await gotoApp(page, "http://tauri.localhost/?e2e=installed-output-recovery");
    await expect(page).toHaveTitle("PDF整理ツール", { timeout: 30_000 });

    await page.getByRole("button", { name: "PDFを選択" }).first().click();
    await expect(page.getByText(basename(pdfPath)).first()).toBeVisible({ timeout: 30_000 });
    await page.getByRole("button", { name: "出力フォルダ" }).click();
    await expect(page.locator('[role="status"]')).toContainText("出力フォルダを設定しました。", { timeout: 30_000 });

    await page.getByRole("button", { name: "分割へ進む" }).click();
    await expect(page.locator('[data-testid="step-split"][aria-current="step"]')).toBeAttached({ timeout: 30_000 });
    await page.getByRole("spinbutton", { name: "ページ番号" }).fill("2");
    await expect(page.getByRole("spinbutton", { name: "ページ番号" })).toHaveValue("2", { timeout: 30_000 });
    await page.getByRole("button", { name: "現在ページの前で分割" }).click();
    await expect(page.locator('[role="status"]')).toContainText("2ページの前に分割を追加しました。", { timeout: 30_000 });
    await page.getByRole("spinbutton", { name: "ページ番号" }).fill("3");
    await expect(page.getByRole("spinbutton", { name: "ページ番号" })).toHaveValue("3", { timeout: 30_000 });
    await page.getByRole("button", { name: "現在ページの前で分割" }).click();
    await expect(page.locator('[role="status"]')).toContainText("3ページの前に分割を追加しました。", { timeout: 30_000 });
    await page.getByRole("button", { name: "入力へ進む" }).click();

    await expect(page.locator('[data-testid="step-input"][aria-current="step"]')).toBeAttached({ timeout: 30_000 });
    await expect(page.locator(".mini-row")).toHaveCount(3, { timeout: 30_000 });
    for (let index = 0; index < 3; index += 1) {
      await page.locator(".mini-row").nth(index).click();
      await page.locator('input[name="box_no"]').fill("1");
      await page.locator('input[name="binder_no"]').fill("1");
      await page.locator('input[name="seq"]').fill(String(index + 1));
    }
    await page.getByRole("button", { name: "出力前チェック" }).last().click();
    await expect(page.locator('[data-testid="step-output"][aria-current="step"]')).toBeAttached({ timeout: 30_000 });
    await expect(page.locator('[role="status"]')).toContainText("出力できます。", { timeout: 30_000 });

    await page.getByRole("button", { name: "出力フォルダを開く" }).click();
    await waitForExplorerFolder(outputDir);
    closeExplorerFolder(outputDir);

    await page.getByRole("button", { name: "出力実行" }).click();
    await expect(page.locator('[role="status"]')).toContainText("出力結果を確認してください（失敗 1件）。", { timeout: 30_000 });
    await expect(page.getByText("作成 2件 / 失敗 1件")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText("simulated locked file").first()).toBeVisible({ timeout: 30_000 });
    await expect(page.locator(".output-list .output-row.created")).toHaveCount(2, { timeout: 30_000 });
    await expect(page.locator(".output-list .output-row.error")).toHaveCount(1, { timeout: 30_000 });

    await page.getByRole("button", { name: "失敗した1件を再出力" }).click();
    await expect(page.locator('[role="status"]')).toContainText("失敗分の再出力が完了しました。", { timeout: 30_000 });
    await expect(page.getByText("作成 3件 / 失敗 0件")).toBeVisible({ timeout: 30_000 });
    await expect(page.locator(".output-list .output-row.created")).toHaveCount(3, { timeout: 30_000 });
    await expect(page.locator(".output-list .output-row.created .state-text")).toHaveText(["作成済み", "作成済み", "作成済み"]);
    await expect(page.getByRole("button", { name: "失敗した1件を再出力" })).toHaveCount(0);
    await page.screenshot({ fullPage: false, path: screenshotPath });

    expect(pageErrors, "Output recovery smoke should not produce page errors").toEqual([]);
    expect(consoleMessages, "Output recovery smoke should not produce console warnings/errors").toEqual([]);

    console.log(
      JSON.stringify(
        {
          ok: true,
          appPath,
          mode: "output-recovery",
          outputDir,
          pdfPath,
          screenshotPath,
          tempRoot: keepTemp ? tempRoot : undefined,
        },
        null,
        2,
      ),
    );
  } finally {
    closeExplorerFolder(outputDir);
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

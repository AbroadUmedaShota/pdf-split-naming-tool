import { chromium, expect } from "@playwright/test";
import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import net from "node:net";

const appPath =
  process.env.PDF_ORGANIZER_INSTALLED_EXE ??
  join(process.env.LOCALAPPDATA ?? "", "PDF整理ツール", "pdf-organizer-desktop.exe");
const keepTemp = process.env.PDF_ORGANIZER_KEEP_NATIVE_DIALOG_TMP === "1";
const screenshotPath =
  process.env.PDF_ORGANIZER_NATIVE_DIALOG_SCREENSHOT ??
  join(tmpdir(), `pdf-tool-installed-native-dialog-${Date.now()}.png`);

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
      { id: 6, body: streamObject("Native dialog smoke page 1") },
      { id: 7, body: streamObject("Native dialog smoke page 2") },
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

function selectPdfInNativeOpenDialog(pdfPath) {
  const script = String.raw`
$PdfPath = $env:PDF_NATIVE_DIALOG_PATH
if ([string]::IsNullOrWhiteSpace($PdfPath)) { throw 'PDF_NATIVE_DIALOG_PATH is empty' }
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Text;
public static class NativeDialogSmokeWin32 {
  public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int count);
  [DllImport("user32.dll")] public static extern int GetClassName(IntPtr hWnd, StringBuilder text, int count);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern IntPtr SendMessage(IntPtr hWnd, int msg, IntPtr wParam, string lParam);
  [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr hWnd, int msg, IntPtr wParam, IntPtr lParam);
}
"@
function Find-OpenDialog {
  $script:found = [IntPtr]::Zero
  [NativeDialogSmokeWin32]::EnumWindows({ param($h, $l)
    if (-not [NativeDialogSmokeWin32]::IsWindowVisible($h)) { return $true }
    $title = New-Object System.Text.StringBuilder 512
    $class = New-Object System.Text.StringBuilder 256
    [void][NativeDialogSmokeWin32]::GetWindowText($h, $title, $title.Capacity)
    [void][NativeDialogSmokeWin32]::GetClassName($h, $class, $class.Capacity)
    if ($class.ToString() -eq '#32770' -and $title.ToString() -match '開く|Open') {
      $script:found = $h
      return $false
    }
    return $true
  }, [IntPtr]::Zero) | Out-Null
  return $script:found
}
$deadline = (Get-Date).AddSeconds(10)
$hwnd = [IntPtr]::Zero
while ((Get-Date) -lt $deadline -and $hwnd -eq [IntPtr]::Zero) {
  $hwnd = Find-OpenDialog
  Start-Sleep -Milliseconds 200
}
if ($hwnd -eq [IntPtr]::Zero) { throw 'Open dialog not found' }
[void][NativeDialogSmokeWin32]::SetForegroundWindow($hwnd)
$dialog = [System.Windows.Automation.AutomationElement]::FromHandle($hwnd)
$all = $dialog.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
$editHwnd = [IntPtr]::Zero
$openHwnd = [IntPtr]::Zero
for ($i = 0; $i -lt $all.Count; $i++) {
  $el = $all.Item($i)
  if ($el.Current.AutomationId -eq '1148' -and $el.Current.ClassName -eq 'Edit') {
    $editHwnd = [IntPtr]$el.Current.NativeWindowHandle
  }
  if ($el.Current.AutomationId -eq '1' -and $el.Current.ClassName -eq 'Button') {
    $openHwnd = [IntPtr]$el.Current.NativeWindowHandle
  }
}
if ($editHwnd -eq [IntPtr]::Zero) { throw 'File name edit not found' }
if ($openHwnd -eq [IntPtr]::Zero) { throw 'Open button not found' }
$WM_SETTEXT = 0x000C
$BM_CLICK = 0x00F5
[void][NativeDialogSmokeWin32]::SendMessage($editHwnd, $WM_SETTEXT, [IntPtr]::Zero, $PdfPath)
Start-Sleep -Milliseconds 200
[void][NativeDialogSmokeWin32]::SendMessage($openHwnd, $BM_CLICK, [IntPtr]::Zero, [IntPtr]::Zero)
Write-Output "selected:$PdfPath"
`;

  const result = spawnSync("powershell", ["-NoProfile", "-Command", script], {
    encoding: "utf8",
    env: { ...process.env, PDF_NATIVE_DIALOG_PATH: pdfPath },
    timeout: 20_000,
  });
  if (result.status !== 0) {
    throw new Error(
      `Native open dialog automation failed.\nstdout:\n${result.stdout}\nstderr:\n${result.stderr}`,
    );
  }
  return result.stdout.trim();
}

function selectOutputDirInNativeFolderDialog(outputDir) {
  const script = String.raw`
$OutputDir = $env:PDF_NATIVE_OUTPUT_DIR
if ([string]::IsNullOrWhiteSpace($OutputDir)) { throw 'PDF_NATIVE_OUTPUT_DIR is empty' }
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Text;
public static class NativeFolderDialogSmokeWin32 {
  public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int count);
  [DllImport("user32.dll")] public static extern int GetClassName(IntPtr hWnd, StringBuilder text, int count);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern IntPtr SendMessage(IntPtr hWnd, int msg, IntPtr wParam, string lParam);
  [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr hWnd, int msg, IntPtr wParam, IntPtr lParam);
}
"@
function Find-FolderDialog {
  $script:found = [IntPtr]::Zero
  [NativeFolderDialogSmokeWin32]::EnumWindows({ param($h, $l)
    if (-not [NativeFolderDialogSmokeWin32]::IsWindowVisible($h)) { return $true }
    $title = New-Object System.Text.StringBuilder 512
    $class = New-Object System.Text.StringBuilder 256
    [void][NativeFolderDialogSmokeWin32]::GetWindowText($h, $title, $title.Capacity)
    [void][NativeFolderDialogSmokeWin32]::GetClassName($h, $class, $class.Capacity)
    if ($class.ToString() -eq '#32770' -and $title.ToString() -match 'フォルダーの選択|Select Folder|Choose Folder') {
      $script:found = $h
      return $false
    }
    return $true
  }, [IntPtr]::Zero) | Out-Null
  return $script:found
}
$deadline = (Get-Date).AddSeconds(10)
$hwnd = [IntPtr]::Zero
while ((Get-Date) -lt $deadline -and $hwnd -eq [IntPtr]::Zero) {
  $hwnd = Find-FolderDialog
  Start-Sleep -Milliseconds 200
}
if ($hwnd -eq [IntPtr]::Zero) { throw 'Folder dialog not found' }
[void][NativeFolderDialogSmokeWin32]::SetForegroundWindow($hwnd)
$dialog = [System.Windows.Automation.AutomationElement]::FromHandle($hwnd)
$all = $dialog.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
$editHwnd = [IntPtr]::Zero
$selectHwnd = [IntPtr]::Zero
for ($i = 0; $i -lt $all.Count; $i++) {
  $el = $all.Item($i)
  if ($el.Current.AutomationId -eq '1152' -and $el.Current.ClassName -eq 'Edit') {
    $editHwnd = [IntPtr]$el.Current.NativeWindowHandle
  }
  if ($el.Current.AutomationId -eq '1' -and $el.Current.ClassName -eq 'Button') {
    $selectHwnd = [IntPtr]$el.Current.NativeWindowHandle
  }
}
if ($editHwnd -eq [IntPtr]::Zero) { throw 'Folder path edit not found' }
if ($selectHwnd -eq [IntPtr]::Zero) { throw 'Select folder button not found' }
$WM_SETTEXT = 0x000C
$BM_CLICK = 0x00F5
[void][NativeFolderDialogSmokeWin32]::SendMessage($editHwnd, $WM_SETTEXT, [IntPtr]::Zero, $OutputDir)
Start-Sleep -Milliseconds 200
[void][NativeFolderDialogSmokeWin32]::SendMessage($selectHwnd, $BM_CLICK, [IntPtr]::Zero, [IntPtr]::Zero)
Write-Output "selected:$OutputDir"
`;

  const result = spawnSync("powershell", ["-NoProfile", "-Command", script], {
    encoding: "utf8",
    env: { ...process.env, PDF_NATIVE_OUTPUT_DIR: outputDir },
    timeout: 20_000,
  });
  if (result.status !== 0) {
    throw new Error(
      `Native folder dialog automation failed.\nstdout:\n${result.stdout}\nstderr:\n${result.stderr}`,
    );
  }
  return result.stdout.trim();
}

async function main() {
  if (!existsSync(appPath)) {
    throw new Error(`Installed app was not found: ${appPath}`);
  }

  const tempRoot = mkdtempSync(join(tmpdir(), "pdf-tool-native-dialog-"));
  const pdfPath = join(tempRoot, "Native Dialog 日本語 path.pdf");
  const outputDir = join(tempRoot, "Native Output 日本語 folder");
  writeSamplePdf(pdfPath);
  mkdirSync(outputDir, { recursive: true });

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

    await page.waitForLoadState("domcontentloaded", { timeout: 30_000 }).catch(() => {});
    await expect(page).toHaveTitle("PDF整理ツール", { timeout: 30_000 });
    await expect(page.getByRole("heading", { name: "PDF整理ツール" })).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText("PDFが未選択です")).toBeVisible();

    await page.getByRole("button", { name: "PDFを選択" }).first().click({ timeout: 5_000 }).catch(() => {});
    const dialogResult = selectPdfInNativeOpenDialog(pdfPath);

    await expect(page.getByText("Native Dialog 日本語 path.pdf").first()).toBeVisible({ timeout: 120_000 });
    await expect(page.getByText("2ページ").first()).toBeVisible({ timeout: 120_000 });
    await expect(page.locator(".queue-row")).toHaveCount(1);
    await expect(page.locator('[role="status"]')).toContainText("1件のPDFを読み込みました。", {
      timeout: 120_000,
    });
    await page.getByRole("button", { name: "出力フォルダ" }).click({ timeout: 10_000 });
    const outputDialogResult = selectOutputDirInNativeFolderDialog(outputDir);
    await expect(page.locator('[role="status"]')).toContainText("出力フォルダを設定しました。", {
      timeout: 30_000,
    });
    await expect(page.getByText(outputDir).first()).toBeVisible({ timeout: 30_000 });
    await page.screenshot({ fullPage: false, path: screenshotPath });

    expect(pageErrors, "Native dialog smoke should not produce page errors").toEqual([]);
    expect(consoleMessages, "Native dialog smoke should not produce console warnings/errors").toEqual([]);

    console.log(
      JSON.stringify(
        {
          ok: true,
          appPath,
          dialogResult,
          outputDialogResult,
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

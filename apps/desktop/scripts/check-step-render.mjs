import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { setTimeout as delay } from "node:timers/promises";

const appUrl = process.env.STEP_RENDER_URL ?? "http://127.0.0.1:3000";
const viewport = { width: 1366, height: 768 };

function devPreviewUrl(step = "split") {
  const url = new URL(appUrl);
  url.searchParams.set("dev", step);
  return url.toString();
}

function chromeCandidates() {
  const programFiles = process.env.ProgramFiles;
  const programFilesX86 = process.env["ProgramFiles(x86)"];
  return [
    process.env.CHROME_PATH,
    programFiles ? join(programFiles, "Google", "Chrome", "Application", "chrome.exe") : "",
    programFilesX86 ? join(programFilesX86, "Google", "Chrome", "Application", "chrome.exe") : "",
    programFiles ? join(programFiles, "Microsoft", "Edge", "Application", "msedge.exe") : "",
    programFilesX86 ? join(programFilesX86, "Microsoft", "Edge", "Application", "msedge.exe") : ""
  ].filter(Boolean);
}

async function fileExists(path) {
  try {
    await import("node:fs/promises").then(({ access }) => access(path));
    return true;
  } catch {
    return false;
  }
}

async function findChrome() {
  for (const candidate of chromeCandidates()) {
    if (await fileExists(candidate)) {
      return candidate;
    }
  }
  throw new Error("Chrome or Edge executable was not found. Set CHROME_PATH to run this check.");
}

function fetchJson(url) {
  return new Promise((resolve, reject) => {
    fetch(url)
      .then((response) => {
        if (!response.ok) {
          throw new Error(`${url} returned HTTP ${response.status}`);
        }
        return response.json();
      })
      .then(resolve, reject);
  });
}

async function waitForJson(url, timeoutMs = 10_000) {
  const started = Date.now();
  let lastError;
  while (Date.now() - started < timeoutMs) {
    try {
      return await fetchJson(url);
    } catch (error) {
      lastError = error;
      await delay(150);
    }
  }
  throw lastError ?? new Error(`${url} did not become available.`);
}

async function assertAppServer() {
  const started = Date.now();
  let lastError;
  while (Date.now() - started < 20_000) {
    try {
      const response = await fetch(appUrl);
      if (response.ok) {
        return;
      }
      lastError = new Error(`${appUrl} returned HTTP ${response.status}`);
    } catch (error) {
      lastError = error;
    }
    await delay(500);
  }
  throw new Error(`${appUrl} must be available before running this render check: ${lastError}`);
}

async function withChrome(callback) {
  const chromePath = await findChrome();
  const userDataDir = await mkdtemp(join(tmpdir(), "pdf-step-render-"));
  const port = 9222 + Math.floor(Math.random() * 1000);
  const chrome = spawn(
    chromePath,
    [
      "--headless=new",
      "--disable-gpu",
      "--disable-extensions",
      "--no-first-run",
      "--no-default-browser-check",
      `--remote-debugging-port=${port}`,
      `--user-data-dir=${userDataDir}`,
      `--window-size=${viewport.width},${viewport.height}`,
      "about:blank"
    ],
    { stdio: ["ignore", "ignore", "pipe"] }
  );

  let stderr = "";
  chrome.stderr?.on("data", (chunk) => {
    stderr += String(chunk);
  });

  try {
    await waitForJson(`http://127.0.0.1:${port}/json/version`);
    return await callback(port);
  } catch (error) {
    error.message = `${error.message}\nChrome stderr:\n${stderr.slice(-2000)}`;
    throw error;
  } finally {
    if (!chrome.killed) {
      chrome.kill();
    }
    await Promise.race([
      new Promise((resolve) => chrome.once("exit", resolve)),
      delay(2_000)
    ]);
    await rm(userDataDir, { force: true, maxRetries: 8, recursive: true, retryDelay: 250 });
  }
}

function connectToCdp(webSocketDebuggerUrl) {
  const socket = new WebSocket(webSocketDebuggerUrl);
  let nextId = 1;
  const pending = new Map();
  const events = [];

  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      const { reject, resolve } = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) {
        reject(new Error(`${message.error.message}: ${message.error.data ?? ""}`));
      } else {
        resolve(message.result);
      }
    } else if (message.method === "Runtime.exceptionThrown" || message.method === "Log.entryAdded") {
      events.push(message);
    }
  });

  return new Promise((resolve, reject) => {
    socket.addEventListener("open", () => {
      resolve({
        close: () => socket.close(),
        events,
        send(method, params = {}) {
          const id = nextId++;
          socket.send(JSON.stringify({ id, method, params }));
          return new Promise((sendResolve, sendReject) => {
            pending.set(id, { reject: sendReject, resolve: sendResolve });
          });
        }
      });
    });
    socket.addEventListener("error", () => reject(new Error("Could not connect to Chrome DevTools Protocol.")));
  });
}

async function openPage(port) {
  const response = await fetch(`http://127.0.0.1:${port}/json/new`, { method: "PUT" });
  assert.equal(response.ok, true, `Chrome target creation failed with HTTP ${response.status}.`);
  return await response.json();
}

async function evaluateLayout(client) {
  const expression = String.raw`
    (async () => {
      const waitFor = async (predicate, label) => {
        const started = Date.now();
        while (Date.now() - started < 20000) {
          const value = predicate();
          if (value) return value;
          await new Promise((resolve) => setTimeout(resolve, 100));
        }
        throw new Error(label + " was not found. Body text: " + document.body.textContent?.slice(0, 500));
      };

      const splitTab = await waitFor(
        () => document.querySelector('[data-testid="step-split"]'),
        "STEP2 tab"
      );
      const main = await waitFor(() => document.querySelector("main.app-shell"), "app shell");
      const started = Date.now();
      while (!main.className.includes("split-screen-shell") && Date.now() - started < 10000) {
        splitTab.click();
        await new Promise((resolve) => setTimeout(resolve, 150));
      }
      await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
      const taskLayout = await waitFor(() => document.querySelector(".task-layout"), "task layout");
      const devSwitcher = await waitFor(() => document.querySelector(".dev-preview-switcher"), "DEV switcher");
      const footerButton = await waitFor(
        () => Array.from(document.querySelectorAll("button")).find((button) => button.textContent?.includes("入力へ進む")),
        "STEP2 footer button"
      ).catch(() => null);
      if (!footerButton) {
        return {
          error: "STEP2 footer button was not found.",
          activeStep: document.querySelector('[data-testid="step-split"]')?.getAttribute("aria-current"),
          buttonTexts: Array.from(document.querySelectorAll("button")).map((button) => button.textContent?.trim()),
          mainClassName: main.className,
          taskClassName: taskLayout.className
        };
      }
      const previewFrame = await waitFor(() => document.querySelector(".split-work .preview-frame"), "preview frame");
      const mainRect = main.getBoundingClientRect();
      const taskRect = taskLayout.getBoundingClientRect();
      const footerRect = footerButton.getBoundingClientRect();
      const previewRect = previewFrame.getBoundingClientRect();
      const docOverflow = Math.max(
        document.documentElement.scrollHeight,
        document.body.scrollHeight
      ) - window.innerHeight;

      return {
        activeStep: document.querySelector('[data-testid="step-split"]')?.getAttribute("aria-current"),
        docOverflow,
        devSwitcherVisible: devSwitcher.getBoundingClientRect().width > 0,
        footerBottom: footerRect.bottom,
        footerTop: footerRect.top,
        footerVisible:
          footerRect.width > 0 &&
          footerRect.height > 0 &&
          footerRect.top >= 0 &&
          footerRect.bottom <= window.innerHeight + 1,
        mainBottom: mainRect.bottom,
        mainClassName: main.className,
        previewHeight: previewRect.height,
        taskBottom: taskRect.bottom,
        taskOverflow: getComputedStyle(taskLayout).overflow,
        viewportHeight: window.innerHeight,
        viewportWidth: window.innerWidth
      };
    })()
  `;

  const result = await client.send("Runtime.evaluate", {
    awaitPromise: true,
    expression,
    returnByValue: true
  });

  if (result.exceptionDetails) {
    throw new Error(result.exceptionDetails.text ?? "Layout evaluation failed.");
  }
  return result.result.value;
}

async function evaluateImportLayout(client) {
  const expression = String.raw`
    (async () => {
      const waitFor = async (predicate, label) => {
        const started = Date.now();
        while (Date.now() - started < 20000) {
          const value = predicate();
          if (value) return value;
          await new Promise((resolve) => setTimeout(resolve, 100));
        }
        throw new Error(label + " was not found. Body text: " + document.body.textContent?.slice(0, 500));
      };

      const main = await waitFor(() => document.querySelector("main.app-shell"), "app shell");
      const taskLayout = await waitFor(() => document.querySelector(".task-layout.import-single-layout"), "STEP1 task layout");
      const continueButton = await waitFor(
        () => Array.from(document.querySelectorAll("button")).find((button) => button.textContent?.includes("分割へ進む")),
        "STEP1 continue button"
      );
      const buttonRect = continueButton.getBoundingClientRect();
      const taskRect = taskLayout.getBoundingClientRect();
      const docOverflow = Math.max(
        document.documentElement.scrollHeight,
        document.body.scrollHeight
      ) - window.innerHeight;

      return {
        activeStep: document.querySelector('[data-testid="step-import"]')?.getAttribute("aria-current"),
        buttonVisible:
          buttonRect.width > 0 &&
          buttonRect.height > 0 &&
          buttonRect.top >= 0 &&
          buttonRect.bottom <= window.innerHeight + 1,
        docOverflow,
        mainClassName: main.className,
        taskBottom: taskRect.bottom,
        viewportHeight: window.innerHeight,
        viewportWidth: window.innerWidth
      };
    })()
  `;

  const result = await client.send("Runtime.evaluate", {
    awaitPromise: true,
    expression,
    returnByValue: true
  });

  if (result.exceptionDetails) {
    throw new Error(result.exceptionDetails.text ?? "STEP1 layout evaluation failed.");
  }
  return result.result.value;
}

async function evaluateDevStep(client, step, expectedText) {
  const expression = `
    (async () => {
      const started = Date.now();
      while (!document.querySelector(".dev-preview-switcher") && Date.now() - started < 10000) {
        await new Promise((resolve) => setTimeout(resolve, 100));
      }
      const activeTab = document.querySelector('[data-testid="step-${step}"]');
      return {
        activeStep: activeTab?.getAttribute("aria-current"),
        bodyText: document.body.textContent ?? "",
        devSwitcherVisible: Boolean(document.querySelector(".dev-preview-switcher")?.getBoundingClientRect().width),
        mainClassName: document.querySelector("main.app-shell")?.className ?? ""
      };
    })()
  `;
  const result = await client.send("Runtime.evaluate", {
    awaitPromise: true,
    expression,
    returnByValue: true
  });
  if (result.exceptionDetails) {
    throw new Error(result.exceptionDetails.text ?? `DEV ${step} evaluation failed.`);
  }
  const value = result.result.value;
  assert.equal(value.activeStep, "step", `DEV ${step} is not active: ${JSON.stringify(value)}`);
  assert.equal(value.devSwitcherVisible, true, `DEV switcher is not visible on ${step}: ${JSON.stringify(value)}`);
  assert.match(value.bodyText, /000高精度ocrのテスト用ファイル_searchable\.pdf/, `Sample PDF is missing on ${step}.`);
  assert.match(value.bodyText, new RegExp(expectedText), `Expected text is missing on ${step}.`);
}

async function main() {
  await assertAppServer();
  await withChrome(async (port) => {
    const target = await openPage(port);
    const client = await connectToCdp(target.webSocketDebuggerUrl);
    try {
      await client.send("Page.enable");
      await client.send("Log.enable");
      await client.send("Runtime.enable");
      await client.send("Emulation.setDeviceMetricsOverride", {
        deviceScaleFactor: 1,
        height: viewport.height,
        mobile: false,
        width: viewport.width
      });
      for (const [step, expectedText] of [
        ["import", "取込設定"],
        ["split", "分割設定"],
        ["input", "命名入力"],
        ["output", "出力確認"]
      ]) {
        await client.send("Page.navigate", { url: devPreviewUrl(step) });
        await delay(1000);
        await evaluateDevStep(client, step, expectedText);
      }
      await client.send("Page.navigate", { url: devPreviewUrl("import") });
      await delay(1000);
      const importLayout = await Promise.race([
        evaluateImportLayout(client),
        delay(15_000).then(() => {
          throw new Error("STEP1 layout evaluation timed out.");
        })
      ]);
      assert.equal(importLayout.viewportWidth, viewport.width);
      assert.equal(importLayout.viewportHeight, viewport.height);
      assert.equal(importLayout.activeStep, "step");
      assert.equal(importLayout.buttonVisible, true, `STEP1 continue button is not fully visible: ${JSON.stringify(importLayout)}`);
      assert.ok(importLayout.taskBottom <= viewport.height + 1, `STEP1 task area exceeds viewport: ${JSON.stringify(importLayout)}`);
      assert.ok(importLayout.docOverflow <= 1, `STEP1 caused outer document scroll: ${JSON.stringify(importLayout)}`);
      await client.send("Page.navigate", { url: devPreviewUrl("split") });
      await delay(1500);
      const layout = await evaluateLayout(client);
      assert.equal(
        layout.error,
        undefined,
        JSON.stringify({ ...layout, cdpEvents: client.events.slice(-10) }, null, 2)
      );
      assert.equal(layout.viewportWidth, viewport.width);
      assert.equal(layout.viewportHeight, viewport.height);
      assert.equal(layout.activeStep, "step");
      assert.equal(layout.devSwitcherVisible, true, `DEV switcher is not visible: ${JSON.stringify(layout)}`);
      assert.match(layout.mainClassName, /split-screen-shell/);
      assert.equal(layout.footerVisible, true, `STEP2 footer is not fully visible: ${JSON.stringify(layout)}`);
      assert.ok(layout.previewHeight > 120, `STEP2 preview is too short: ${JSON.stringify(layout)}`);
      assert.ok(layout.mainBottom <= viewport.height + 1, `STEP2 shell exceeds viewport: ${JSON.stringify(layout)}`);
      assert.ok(layout.taskBottom <= viewport.height + 1, `STEP2 task area exceeds viewport: ${JSON.stringify(layout)}`);
      assert.ok(layout.docOverflow <= 1, `STEP2 caused outer document scroll: ${JSON.stringify(layout)}`);
      assert.equal(layout.taskOverflow, "hidden");
      await writeFile(join(tmpdir(), "pdf-step-render-result.json"), JSON.stringify(layout, null, 2));
      console.log(`[check-step-render] passed ${viewport.width}x${viewport.height} STEP2 layout smoke.`);
    } finally {
      client.close();
    }
  });
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});

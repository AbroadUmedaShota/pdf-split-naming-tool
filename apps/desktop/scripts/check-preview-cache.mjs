import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const ts = require("typescript");

const __dirname = dirname(fileURLToPath(import.meta.url));
const compilerOptions = {
  module: ts.ModuleKind.CommonJS,
  target: ts.ScriptTarget.ES2022,
};

function loadTsModule(sourcePath, moduleRequire = require) {
  const source = readFileSync(sourcePath, "utf8");
  const transpiled = ts.transpileModule(source, { compilerOptions });
  const module = { exports: {} };
  const compile = new Function("exports", "require", "module", "__filename", "__dirname", transpiled.outputText);
  compile(module.exports, moduleRequire, module, sourcePath, dirname(sourcePath));
  return module.exports;
}

const previewCachePath = join(__dirname, "..", "lib", "preview-cache.ts");
const previewCacheModule = loadTsModule(previewCachePath);
const previewFlowPath = join(__dirname, "..", "lib", "preview-flow.ts");
const previewFlowModule = loadTsModule(previewFlowPath, (specifier) => {
  if (specifier === "./preview-cache") {
    return previewCacheModule;
  }
  return require(specifier);
});

const { createPreviewCache, createPreviewRequestGate } = previewCacheModule;
const { loadPagePreview, hasPreviewImageData } = previewFlowModule;

// プレビュー/サムネイル共通の data URL 検証（page_thumbnail 取得側でも使用）。
assert.equal(hasPreviewImageData("data:image/jpeg;base64,abc"), true);
assert.equal(hasPreviewImageData("data:image/png;base64,abc"), true);
assert.equal(hasPreviewImageData("data:image/jpeg;base64,"), false); // 本体なしは不可
assert.equal(hasPreviewImageData("data:image/gif;base64,abc"), false); // 想定外形式は不可
assert.equal(hasPreviewImageData(""), false);

function createDeferred() {
  let resolve;
  let reject;
  const promise = new Promise((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, reject, resolve };
}

async function withTimeout(promise, label, timeoutMs = 1000) {
  let timeout;
  try {
    return await Promise.race([
      promise,
      new Promise((_, reject) => {
        timeout = setTimeout(() => reject(new Error(`${label} timed out after ${timeoutMs}ms`)), timeoutMs);
      }),
    ]);
  } finally {
    clearTimeout(timeout);
  }
}

async function assertRejectedPreviewResponse({
  expectedMessage,
  label,
  pageNo = 2,
  response,
  responseErrorMessage,
}) {
  const cache = createPreviewCache(5);
  const gate = createPreviewRequestGate();
  const appliedPreviews = [];
  const sidecarRequests = [];
  const pdfPath = `C:\\docs\\rejected-${label}.pdf`;

  await assert.rejects(
    loadPagePreview({
      applyPreview: (preview) => appliedPreviews.push(preview),
      cache,
      gate,
      invalidPreviewMessage: "invalid preview",
      pageNo,
      pdfPath,
      requestPreview: async (request) => {
        sidecarRequests.push(request);
        return response;
      },
      responseErrorMessage,
    }),
    expectedMessage
  );

  assert.deepEqual(sidecarRequests, [{ command: "page_preview", pdf_path: pdfPath, page_no: pageNo }]);
  assert.equal(cache.get(pdfPath, pageNo), null);
  assert.deepEqual(appliedPreviews, []);
}

{
  const cache = createPreviewCache(3);

  cache.set("C:\\docs\\a.pdf", 1, { imageDataUrl: "data:image/png;base64,a1", pageNo: 1 });

  assert.deepEqual(cache.get("C:\\docs\\a.pdf", 1), {
    imageDataUrl: "data:image/png;base64,a1",
    pageNo: 1,
  });
  assert.equal(cache.get("C:\\docs\\a.pdf", 2), null);
}

{
  const cache = createPreviewCache(2);

  cache.set("C:\\docs\\a.pdf", 1, { imageDataUrl: "a1", pageNo: 1 });
  cache.set("C:\\docs\\b.pdf", 1, { imageDataUrl: "b1", pageNo: 1 });
  assert.equal(cache.get("C:\\docs\\a.pdf", 1)?.imageDataUrl, "a1");
  cache.set("C:\\docs\\c.pdf", 1, { imageDataUrl: "c1", pageNo: 1 });

  assert.equal(cache.get("C:\\docs\\b.pdf", 1), null);
  assert.equal(cache.get("C:\\docs\\a.pdf", 1)?.imageDataUrl, "a1");
  assert.equal(cache.get("C:\\docs\\c.pdf", 1)?.imageDataUrl, "c1");
  assert.equal(cache.size(), 2);
}

{
  const cache = createPreviewCache(4);
  const pdfPath = "C:\\docs\\large.pdf";

  for (let pageNo = 1; pageNo <= 4; pageNo += 1) {
    cache.set(pdfPath, pageNo, { imageDataUrl: `page-${pageNo}`, pageNo });
  }

  assert.equal(cache.get(pdfPath, 1)?.imageDataUrl, "page-1");
  assert.equal(cache.get(pdfPath, 2)?.imageDataUrl, "page-2");

  cache.set(pdfPath, 5, { imageDataUrl: "page-5", pageNo: 5 });
  cache.set(pdfPath, 6, { imageDataUrl: "page-6", pageNo: 6 });

  assert.equal(cache.get(pdfPath, 3), null);
  assert.equal(cache.get(pdfPath, 4), null);
  assert.equal(cache.get(pdfPath, 1)?.imageDataUrl, "page-1");
  assert.equal(cache.get(pdfPath, 2)?.imageDataUrl, "page-2");
  assert.equal(cache.get(pdfPath, 5)?.imageDataUrl, "page-5");
  assert.equal(cache.get(pdfPath, 6)?.imageDataUrl, "page-6");
  assert.equal(cache.size(), 4);
}

{
  const cache = createPreviewCache(6);
  const pdfPath = "C:\\docs\\large.pdf";

  for (let pageNo = 1; pageNo <= 50; pageNo += 1) {
    cache.set(pdfPath, pageNo, { imageDataUrl: `page-${pageNo}`, pageNo });
    assert.equal(cache.size() <= 6, true);
  }

  for (let pageNo = 45; pageNo <= 50; pageNo += 1) {
    assert.equal(cache.get(pdfPath, pageNo)?.imageDataUrl, `page-${pageNo}`);
  }

  assert.equal(cache.get(pdfPath, 44), null);
  assert.equal(cache.get(pdfPath, 1), null);
}

{
  const cache = createPreviewCache(5);

  cache.set("C:\\docs\\a.pdf", 1, { imageDataUrl: "a1", pageNo: 1 });
  cache.set("C:\\docs\\a.pdf", 2, { imageDataUrl: "a2", pageNo: 2 });
  cache.set("C:\\docs\\a.pdf.backup", 1, { imageDataUrl: "backup1", pageNo: 1 });
  cache.set("C:\\docs\\b.pdf", 1, { imageDataUrl: "b1", pageNo: 1 });

  cache.clearPdf("C:\\docs\\a.pdf");

  assert.equal(cache.get("C:\\docs\\a.pdf", 1), null);
  assert.equal(cache.get("C:\\docs\\a.pdf", 2), null);
  assert.equal(cache.get("C:\\docs\\a.pdf.backup", 1)?.imageDataUrl, "backup1");
  assert.equal(cache.get("C:\\docs\\b.pdf", 1)?.imageDataUrl, "b1");
}

{
  const cache = createPreviewCache(5);

  cache.set("C:\\docs\\a#draft.pdf", 1, { imageDataUrl: "hash1", pageNo: 1 });
  cache.set("C:\\docs\\a#draft.pdf.backup", 1, { imageDataUrl: "backup1", pageNo: 1 });

  cache.clearPdf("C:\\docs\\a#draft.pdf");

  assert.equal(cache.get("C:\\docs\\a#draft.pdf", 1), null);
  assert.equal(cache.get("C:\\docs\\a#draft.pdf.backup", 1)?.imageDataUrl, "backup1");
}

{
  const gate = createPreviewRequestGate();
  const firstRequest = gate.next();
  const secondRequest = gate.next();

  assert.equal(gate.isCurrent(firstRequest), false);
  assert.equal(gate.isCurrent(secondRequest), true);

  gate.invalidate();

  assert.equal(gate.isCurrent(secondRequest), false);
}

{
  const gate = createPreviewRequestGate();
  const requestIds = [];

  for (let pageNo = 1; pageNo <= 100; pageNo += 1) {
    requestIds.push(gate.next());
  }

  const latestRequest = requestIds.at(-1);
  assert.equal(gate.isCurrent(latestRequest), true);

  for (const staleRequest of requestIds.slice(0, -1)) {
    assert.equal(gate.isCurrent(staleRequest), false);
  }

  gate.invalidate();

  assert.equal(gate.isCurrent(latestRequest), false);
}

{
  const cache = createPreviewCache(5);
  const gate = createPreviewRequestGate();
  const appliedPreviews = [];
  const sidecarRequests = [];
  const pdfPath = "C:\\docs\\preview.pdf";

  const firstResult = await loadPagePreview({
    applyPreview: (preview) => appliedPreviews.push(preview),
    cache,
    gate,
    pageNo: 2,
    pdfPath,
    requestPreview: async (request) => {
      sidecarRequests.push(request);
      return {
        ok: true,
        command: "page_preview",
        pdf_path: request.pdf_path,
        page_no: request.page_no,
        page_count: 8,
        image_data_url: "data:image/png;base64,page-2",
      };
    },
  });

  assert.equal(firstResult, "sidecar");
  assert.deepEqual(sidecarRequests, [{ command: "page_preview", pdf_path: pdfPath, page_no: 2 }]);
  assert.deepEqual(appliedPreviews, [{ imageDataUrl: "data:image/png;base64,page-2", pageNo: 2 }]);
  assert.deepEqual(cache.get(pdfPath, 2), { imageDataUrl: "data:image/png;base64,page-2", pageNo: 2 });

  const secondResult = await loadPagePreview({
    applyPreview: (preview) => appliedPreviews.push(preview),
    cache,
    gate,
    pageNo: 2,
    pdfPath,
    requestPreview: async (request) => {
      sidecarRequests.push(request);
      throw new Error("cache hit should not call sidecar");
    },
  });

  assert.equal(secondResult, "cache");
  assert.deepEqual(sidecarRequests, [{ command: "page_preview", pdf_path: pdfPath, page_no: 2 }]);
  assert.deepEqual(appliedPreviews.at(-1), { imageDataUrl: "data:image/png;base64,page-2", pageNo: 2 });
}

{
  // 実サイドカー(pdf_service.py)は page_preview を JPEG で返す。JPEG が受理されることの回帰テスト。
  const cache = createPreviewCache(5);
  const gate = createPreviewRequestGate();
  const appliedPreviews = [];
  const pdfPath = "C:\\docs\\jpeg.pdf";

  const result = await loadPagePreview({
    applyPreview: (preview) => appliedPreviews.push(preview),
    cache,
    gate,
    pageNo: 1,
    pdfPath,
    requestPreview: async () => ({
      ok: true,
      command: "page_preview",
      page_no: 1,
      page_count: 3,
      image_data_url: "data:image/jpeg;base64,jpeg-1",
    }),
  });

  assert.equal(result, "sidecar");
  assert.deepEqual(appliedPreviews, [{ imageDataUrl: "data:image/jpeg;base64,jpeg-1", pageNo: 1 }]);
  assert.deepEqual(cache.get(pdfPath, 1), { imageDataUrl: "data:image/jpeg;base64,jpeg-1", pageNo: 1 });
}

for (const { label, response } of [
  {
    label: "missing image URL",
    response: {
      ok: true,
      command: "page_preview",
      page_count: 8,
      page_no: 2,
    },
  },
  {
    label: "empty PNG payload",
    response: {
      ok: true,
      command: "page_preview",
      image_data_url: "data:image/png;base64,",
      page_count: 8,
      page_no: 2,
    },
  },
  {
    label: "wrong data URL prefix",
    response: {
      ok: true,
      command: "page_preview",
      image_data_url: "data:image/gif;base64,page-2",
      page_count: 8,
      page_no: 2,
    },
  },
  {
    label: "missing page number",
    response: {
      ok: true,
      command: "page_preview",
      image_data_url: "data:image/png;base64,page-2",
      page_count: 8,
    },
  },
  {
    label: "non-number page number",
    response: {
      ok: true,
      command: "page_preview",
      image_data_url: "data:image/png;base64,page-2",
      page_count: 8,
      page_no: "2",
    },
  },
  {
    label: "NaN page number",
    response: {
      ok: true,
      command: "page_preview",
      image_data_url: "data:image/png;base64,page-2",
      page_count: 8,
      page_no: NaN,
    },
  },
  {
    label: "Infinity page number",
    response: {
      ok: true,
      command: "page_preview",
      image_data_url: "data:image/png;base64,page-2",
      page_count: 8,
      page_no: Infinity,
    },
  },
  {
    label: "fractional page number",
    response: {
      ok: true,
      command: "page_preview",
      image_data_url: "data:image/png;base64,page-2",
      page_count: 8,
      page_no: 2.5,
    },
  },
  {
    label: "zero page number",
    response: {
      ok: true,
      command: "page_preview",
      image_data_url: "data:image/png;base64,page-2",
      page_count: 8,
      page_no: 0,
    },
  },
  {
    label: "negative page number",
    response: {
      ok: true,
      command: "page_preview",
      image_data_url: "data:image/png;base64,page-2",
      page_count: 8,
      page_no: -1,
    },
  },
  {
    label: "mismatched page number",
    response: {
      ok: true,
      command: "page_preview",
      image_data_url: "data:image/png;base64,page-3",
      page_count: 8,
      page_no: 3,
    },
  },
  {
    label: "missing page count",
    response: {
      ok: true,
      command: "page_preview",
      image_data_url: "data:image/png;base64,page-2",
      page_no: 2,
    },
  },
  {
    label: "non-number page count",
    response: {
      ok: true,
      command: "page_preview",
      image_data_url: "data:image/png;base64,page-2",
      page_count: "8",
      page_no: 2,
    },
  },
  {
    label: "bool page count",
    response: {
      ok: true,
      command: "page_preview",
      image_data_url: "data:image/png;base64,page-2",
      page_count: true,
      page_no: 2,
    },
  },
  {
    label: "NaN page count",
    response: {
      ok: true,
      command: "page_preview",
      image_data_url: "data:image/png;base64,page-2",
      page_count: NaN,
      page_no: 2,
    },
  },
  {
    label: "Infinity page count",
    response: {
      ok: true,
      command: "page_preview",
      image_data_url: "data:image/png;base64,page-2",
      page_count: Infinity,
      page_no: 2,
    },
  },
  {
    label: "fractional page count",
    response: {
      ok: true,
      command: "page_preview",
      image_data_url: "data:image/png;base64,page-2",
      page_count: 8.5,
      page_no: 2,
    },
  },
  {
    label: "zero page count",
    response: {
      ok: true,
      command: "page_preview",
      image_data_url: "data:image/png;base64,page-2",
      page_count: 0,
      page_no: 2,
    },
  },
  {
    label: "negative page count",
    response: {
      ok: true,
      command: "page_preview",
      image_data_url: "data:image/png;base64,page-2",
      page_count: -1,
      page_no: 2,
    },
  },
]) {
  await assertRejectedPreviewResponse({ expectedMessage: /invalid preview/, label, response });
}

{
  await assertRejectedPreviewResponse({
    expectedMessage: /invalid preview/,
    label: "page number beyond page count",
    pageNo: 5,
    response: {
      ok: true,
      command: "page_preview",
      image_data_url: "data:image/png;base64,page-5",
      page_count: 4,
      page_no: 5,
    },
  });
}

{
  await assertRejectedPreviewResponse({
    expectedMessage: /sidecar failed/,
    label: "error response",
    response: {
      ok: false,
      command: "page_preview",
      error: "raw sidecar error",
    },
    responseErrorMessage: (response) => `sidecar failed: ${response.error}`,
  });
}

{
  await assertRejectedPreviewResponse({
    expectedMessage: /invalid preview/,
    label: "wrong command",
    response: {
      ok: true,
      command: "other_command",
      image_data_url: "data:image/png;base64,page-2",
      page_no: 2,
    },
  });
}

{
  const cache = createPreviewCache(5);
  const gate = createPreviewRequestGate();
  const appliedPreviews = [];
  const sidecarRequests = [];
  const firstResponse = createDeferred();
  const secondResponse = createDeferred();
  const pdfPath = "C:\\docs\\race.pdf";

  const firstLoad = loadPagePreview({
    applyPreview: (preview) => appliedPreviews.push(preview),
    cache,
    gate,
    pageNo: 1,
    pdfPath,
    requestPreview: async (request) => {
      sidecarRequests.push(request);
      return firstResponse.promise;
    },
  });

  const secondLoad = loadPagePreview({
    applyPreview: (preview) => appliedPreviews.push(preview),
    cache,
    gate,
    pageNo: 3,
    pdfPath,
    requestPreview: async (request) => {
      sidecarRequests.push(request);
      return secondResponse.promise;
    },
  });

  assert.deepEqual(sidecarRequests, [
    { command: "page_preview", pdf_path: pdfPath, page_no: 1 },
    { command: "page_preview", pdf_path: pdfPath, page_no: 3 },
  ]);

  firstResponse.resolve({
    ok: true,
    command: "page_preview",
    pdf_path: pdfPath,
    page_no: 1,
    page_count: 8,
    image_data_url: "data:image/png;base64,stale-page-1",
  });

  assert.equal(await withTimeout(firstLoad, "stale preview request"), "stale");
  assert.equal(cache.get(pdfPath, 1), null);
  assert.deepEqual(appliedPreviews, []);

  secondResponse.resolve({
    ok: true,
    command: "page_preview",
    pdf_path: pdfPath,
    page_no: 3,
    page_count: 8,
    image_data_url: "data:image/png;base64,current-page-3",
  });

  assert.equal(await withTimeout(secondLoad, "current preview request"), "sidecar");
  assert.equal(cache.get(pdfPath, 1), null);
  assert.deepEqual(cache.get(pdfPath, 3), { imageDataUrl: "data:image/png;base64,current-page-3", pageNo: 3 });
  assert.deepEqual(appliedPreviews, [{ imageDataUrl: "data:image/png;base64,current-page-3", pageNo: 3 }]);
}

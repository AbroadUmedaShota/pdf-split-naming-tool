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
const { loadPagePreview } = previewFlowModule;

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

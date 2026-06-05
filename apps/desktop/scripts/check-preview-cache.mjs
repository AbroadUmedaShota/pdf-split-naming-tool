import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const ts = require("typescript");

const __dirname = dirname(fileURLToPath(import.meta.url));
const sourcePath = join(__dirname, "..", "lib", "preview-cache.ts");
const source = readFileSync(sourcePath, "utf8");
const transpiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2022,
  },
});

const previewCacheModule = { exports: {} };
const compile = new Function("exports", "require", "module", "__filename", "__dirname", transpiled.outputText);
compile(previewCacheModule.exports, require, previewCacheModule, sourcePath, dirname(sourcePath));

const { createPreviewCache, createPreviewRequestGate } = previewCacheModule.exports;

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

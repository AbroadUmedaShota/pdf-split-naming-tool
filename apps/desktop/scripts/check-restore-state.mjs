import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const ts = require("typescript");

const __dirname = dirname(fileURLToPath(import.meta.url));
const sourcePath = join(__dirname, "..", "lib", "restore-state.ts");
const source = readFileSync(sourcePath, "utf8");
const transpiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2022,
  },
});

const restoreStateModule = { exports: {} };
const compile = new Function("exports", "require", "module", "__filename", "__dirname", transpiled.outputText);
compile(restoreStateModule.exports, require, restoreStateModule, sourcePath, dirname(sourcePath));

const {
  missingPdfStatus,
  resolveMissingSavedPdfRestore,
  restorableInputPaths,
} = restoreStateModule.exports;

assert.deepEqual(
  restorableInputPaths(["C:\\docs\\a.pdf", "C:\\docs\\b.pdf"], ["C:\\docs\\b.pdf"]),
  ["C:\\docs\\a.pdf"],
);

assert.deepEqual(
  restorableInputPaths(
    ["C:\\docs\\z.pdf", "C:\\docs\\a.pdf", "C:\\docs\\m.pdf", "C:\\docs\\b.pdf"],
    ["C:\\docs\\a.pdf", "C:\\docs\\b.pdf"],
  ),
  ["C:\\docs\\z.pdf", "C:\\docs\\m.pdf"],
);

{
  const savedInputPaths = [
    "C:\\docs\\first.pdf",
    "C:\\docs\\missing-middle.pdf",
    "C:\\docs\\second.pdf",
    "C:\\docs\\missing-last.pdf",
    "C:\\docs\\third.pdf",
  ];

  assert.deepEqual(
    restorableInputPaths(savedInputPaths, [
      "C:\\docs\\missing-last.pdf",
      "C:\\docs\\missing-middle.pdf",
    ]),
    ["C:\\docs\\first.pdf", "C:\\docs\\second.pdf", "C:\\docs\\third.pdf"],
  );
}

{
  const decision = resolveMissingSavedPdfRestore({
    currentPage: 4,
    currentPdf: "C:\\docs\\a.pdf",
    hasMissingInputPdf: true,
    loadedPdfFiles: [],
    missingInputPaths: ["C:\\docs\\a.pdf"],
    savedInputPaths: ["C:\\docs\\a.pdf"],
  });

  assert.equal(decision.currentPdf, "");
  assert.equal(decision.currentPage, 1);
  assert.equal(decision.shouldLoadPreview, false);
  assert.deepEqual(decision.restorableInputPaths, []);
  assert.equal(decision.missingStatusInput?.allMissing, true);
  assert.match(decision.statusText, /保存済みPDFが見つかりません/);
  assert.match(decision.statusText, /a\.pdf/);
}

{
  const decision = resolveMissingSavedPdfRestore({
    currentPage: 99,
    currentPdf: "C:\\docs\\a.pdf",
    hasMissingInputPdf: true,
    loadedPdfFiles: [{ path: "C:\\docs\\a.pdf", pageCount: 3 }],
    missingInputPaths: ["C:\\docs\\b.pdf"],
    savedInputPaths: ["C:\\docs\\a.pdf", "C:\\docs\\b.pdf"],
  });

  assert.equal(decision.currentPdf, "C:\\docs\\a.pdf");
  assert.equal(decision.currentPage, 3);
  assert.equal(decision.shouldLoadPreview, true);
  assert.deepEqual(decision.restorableInputPaths, ["C:\\docs\\a.pdf"]);
  assert.equal(decision.missingStatusInput?.allMissing, false);
  assert.match(decision.statusText, /一部の保存済みPDFが見つかりません/);
}

{
  const decision = resolveMissingSavedPdfRestore({
    currentPage: 2,
    currentPdf: "C:\\docs\\b.pdf",
    hasMissingInputPdf: true,
    loadedPdfFiles: [{ path: "C:\\docs\\a.pdf", pageCount: 2 }],
    missingInputPaths: ["C:\\docs\\b.pdf"],
    savedInputPaths: ["C:\\docs\\a.pdf", "C:\\docs\\b.pdf"],
  });

  assert.equal(decision.currentPdf, "C:\\docs\\a.pdf");
  assert.equal(decision.currentPage, 2);
  assert.equal(decision.shouldLoadPreview, true);
  assert.deepEqual(decision.restorableInputPaths, ["C:\\docs\\a.pdf"]);
}

{
  const decision = resolveMissingSavedPdfRestore({
    currentPage: 5,
    currentPdf: "C:\\docs\\missing-current.pdf",
    hasMissingInputPdf: true,
    loadedPdfFiles: [
      { path: "C:\\docs\\third.pdf", pageCount: 8 },
      { path: "C:\\docs\\first.pdf", pageCount: 3 },
      { path: "C:\\docs\\second.pdf", pageCount: 10 },
    ],
    missingInputPaths: ["C:\\docs\\missing-current.pdf"],
    savedInputPaths: [
      "C:\\docs\\missing-current.pdf",
      "C:\\docs\\first.pdf",
      "C:\\docs\\second.pdf",
      "C:\\docs\\third.pdf",
    ],
  });

  assert.equal(decision.currentPdf, "C:\\docs\\first.pdf");
  assert.equal(decision.currentPage, 3);
  assert.equal(decision.shouldLoadPreview, true);
  assert.deepEqual(decision.restorableInputPaths, [
    "C:\\docs\\first.pdf",
    "C:\\docs\\second.pdf",
    "C:\\docs\\third.pdf",
  ]);
}

{
  const decision = resolveMissingSavedPdfRestore({
    currentPage: 2,
    currentPdf: "C:\\docs\\missing-current.pdf",
    hasMissingInputPdf: true,
    loadedPdfFiles: [
      { path: "C:\\docs\\third.pdf", pageCount: 9 },
      { path: "C:\\docs\\second.pdf", pageCount: 7 },
      { path: "C:\\docs\\first.pdf", pageCount: 4 },
    ],
    missingInputPaths: ["C:\\docs\\missing-current.pdf", "C:\\docs\\missing-middle.pdf"],
    savedInputPaths: [
      "C:\\docs\\missing-current.pdf",
      "C:\\docs\\first.pdf",
      "C:\\docs\\missing-middle.pdf",
      "C:\\docs\\second.pdf",
      "C:\\docs\\third.pdf",
    ],
  });

  assert.equal(decision.currentPdf, "C:\\docs\\first.pdf");
  assert.equal(decision.currentPage, 2);
  assert.deepEqual(decision.restorableInputPaths, [
    "C:\\docs\\first.pdf",
    "C:\\docs\\second.pdf",
    "C:\\docs\\third.pdf",
  ]);
}

assert.equal(
  missingPdfStatus({ allMissing: false, paths: ["C:\\docs\\a.pdf", "C:\\docs\\b.pdf", "C:\\docs\\c.pdf"] }),
  "一部の保存済みPDFが見つかりません（a.pdf、b.pdf ほか1件）。再選択してください。",
);

assert.equal(
  missingPdfStatus({ allMissing: true, paths: ["C:\\docs\\a.pdf"] }),
  "保存済みPDFが見つかりません（a.pdf）。再選択してください。",
);

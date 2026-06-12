import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const ts = require("typescript");

const __dirname = dirname(fileURLToPath(import.meta.url));
const sourcePath = join(__dirname, "..", "lib", "output-state.ts");
const source = readFileSync(sourcePath, "utf8");
const transpiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2022,
  },
});

const outputStateModule = { exports: {} };
const compile = new Function("exports", "require", "module", "__filename", "__dirname", transpiled.outputText);
compile(outputStateModule.exports, require, outputStateModule, sourcePath, dirname(sourcePath));

const {
  isOutputCheckOk,
  isOutputCheckRenamed,
  outputDetailStateText,
  outputIssueCount,
  outputListStateText,
} = outputStateModule.exports;

const preflightOk = {
  ok: true,
  filename: "01_02_003.pdf",
  output_path: "C:\\out\\01_02_003.pdf",
  messages: [],
  requested_filename: "01_02_003.pdf",
  requested_path: "C:\\out\\01_02_003.pdf",
  existing_path: "",
  has_existing_output: false,
  metadata: {},
  pages: "1",
  pdf_path: "C:\\docs\\source.pdf",
};

const exportFailedAfterPreflight = {
  ...preflightOk,
  status: "failed",
  error: "Output path already exists: C:\\out\\01_02_003.pdf",
  error_type: "FileExistsError",
};

const preflightInvalid = {
  ...preflightOk,
  ok: false,
  messages: ["連番 is required"],
};

assert.equal(isOutputCheckOk(preflightOk), true);
assert.equal(outputListStateText(preflightOk), "出力可能");
assert.equal(outputDetailStateText(preflightOk), "出力可能");

assert.equal(isOutputCheckOk(exportFailedAfterPreflight), false);
assert.equal(outputListStateText(exportFailedAfterPreflight), "出力失敗");
assert.equal(outputDetailStateText(exportFailedAfterPreflight), "Output path already exists: C:\\out\\01_02_003.pdf");

assert.equal(isOutputCheckOk(preflightInvalid), false);
assert.equal(outputListStateText(preflightInvalid), "要修正");
assert.equal(outputDetailStateText(preflightInvalid), "連番 is required");
assert.equal(outputIssueCount([preflightOk, exportFailedAfterPreflight, preflightInvalid]), 2);

// batch-duplicate: ok のまま予約採番（_2）で別名になった行は warning として可視化する
const preflightRenamed = {
  ...preflightOk,
  filename: "01_02_003_2.pdf",
  output_path: "C:\\out\\01_02_003_2.pdf",
};

assert.equal(isOutputCheckRenamed(preflightOk), false);
assert.equal(isOutputCheckRenamed(preflightRenamed), true);
assert.equal(isOutputCheckOk(preflightRenamed), true);
assert.equal(outputListStateText(preflightRenamed), "同名のため別名採番");
assert.equal(outputDetailStateText(preflightRenamed), "バッチ内で同名のため「01_02_003_2.pdf」を採番");
// 採番済みでも ok 行なので issue には数えない（出力自体は可能）
assert.equal(outputIssueCount([preflightRenamed]), 0);

// filename が空（失敗行など）は採番扱いにしない
assert.equal(isOutputCheckRenamed({ ...preflightOk, filename: "" }), false);

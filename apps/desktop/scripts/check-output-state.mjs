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
  isOutputItemCreated,
  mergeRetriedExport,
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

// 出力完了後の created 行は「出力可能」ではなく「作成済み」として可視化する
const exportCreated = { ...preflightOk, status: "created", sha256: "abc" };
assert.equal(isOutputItemCreated(exportCreated), true);
assert.equal(isOutputItemCreated(preflightOk), false);
assert.equal(isOutputCheckOk(exportCreated), true);
assert.equal(outputListStateText(exportCreated), "作成済み");
assert.equal(outputDetailStateText(exportCreated), "作成済み");
// created かつ別名採番された行は採番済みであることも明示する
const exportCreatedRenamed = { ...exportCreated, filename: "01_02_003_2.pdf" };
assert.equal(outputListStateText(exportCreatedRenamed), "作成済み（別名採番）");
assert.equal(outputDetailStateText(exportCreatedRenamed), "作成済み（別名「01_02_003_2.pdf」で採番）");
// created 行は issue に数えない（出力は成功している）
assert.equal(outputIssueCount([exportCreated]), 0);

// mergeRetriedExport: 「失敗分のみ再出力」の結果を初回出力へマージする
const createdItem = (name, page) => ({
  ...preflightOk,
  status: "created",
  filename: name,
  pages: page,
  sha256: "x",
});
const failedItem = (name, page, error) => ({
  ...preflightOk,
  status: "failed",
  filename: name,
  pages: page,
  error,
});

// 初回: 3件中 index1 が失敗
const baseExport = {
  ok: false,
  command: "export",
  output_dir: "C:\\out",
  summary: { created: 2, failed: 1 },
  items: [createdItem("01.pdf", "1"), failedItem("02.pdf", "2", "locked"), createdItem("03.pdf", "3")],
  messages: ["export_incomplete"],
};

// 再出力で index1 が成功 → 全成功
const retrySuccess = {
  ok: true,
  command: "export",
  output_dir: "C:\\out",
  summary: { created: 1, failed: 0 },
  items: [createdItem("02.pdf", "2")],
  messages: [],
};
const mergedOk = mergeRetriedExport(baseExport, retrySuccess, [1]);
assert.equal(mergedOk.summary.created, 3);
assert.equal(mergedOk.summary.failed, 0);
assert.equal(mergedOk.ok, true);
assert.deepEqual(mergedOk.messages, []);
assert.equal(mergedOk.output_dir, "C:\\out");
// 成功済み行(0,2)は温存、失敗位置(1)だけ差し替え
assert.equal(mergedOk.items[0].filename, "01.pdf");
assert.equal(mergedOk.items[2].filename, "03.pdf");
assert.equal(mergedOk.items[1].status, "created");

// 再出力でも index1 が失敗 → 一部失敗のまま
const retryStillFails = {
  ok: false,
  command: "export",
  output_dir: "C:\\out",
  summary: { created: 0, failed: 1 },
  items: [failedItem("02.pdf", "2", "still locked")],
  messages: [],
};
const mergedFail = mergeRetriedExport(baseExport, retryStillFails, [1]);
assert.equal(mergedFail.summary.created, 2);
assert.equal(mergedFail.summary.failed, 1);
assert.equal(mergedFail.ok, false);
assert.deepEqual(mergedFail.messages, ["export_incomplete"]);
assert.equal(mergedFail.items[1].error, "still locked");

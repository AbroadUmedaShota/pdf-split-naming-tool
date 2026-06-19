import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const ts = require("typescript");

const __dirname = dirname(fileURLToPath(import.meta.url));
const sourcePath = join(__dirname, "..", "lib", "save-state.ts");
const source = readFileSync(sourcePath, "utf8");
const transpiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2022,
  },
});

const saveStateModule = { exports: {} };
const compile = new Function("exports", "require", "module", "__filename", "__dirname", transpiled.outputText);
compile(saveStateModule.exports, require, saveStateModule, sourcePath, dirname(sourcePath));

const { buildSaveStateFilter, shouldRetainSegmentKey } = saveStateModule.exports;

// --- buildSaveStateFilter ---

// ケース1: savedInputPaths が空（セッション開始直後・loadState 未実行）
// → pdfFiles のパスがそのまま input_paths になり、orphan なし
{
  const result = buildSaveStateFilter({
    loadedPdfPaths: ["C:\\docs\\a.pdf", "C:\\docs\\b.pdf"],
    savedInputPaths: [],
  });
  assert.deepEqual(result.orderedInputPaths, ["C:\\docs\\a.pdf", "C:\\docs\\b.pdf"]);
  assert.equal(result.allowedPdfPaths.has("C:\\docs\\a.pdf"), true);
  assert.equal(result.allowedPdfPaths.has("C:\\docs\\b.pdf"), true);
}

// ケース2: 全PDFが正常にロードされている（欠損なし）
// → orderedInputPaths は savedInputPaths の順序を維持
{
  const result = buildSaveStateFilter({
    loadedPdfPaths: ["C:\\docs\\a.pdf", "C:\\docs\\b.pdf"],
    savedInputPaths: ["C:\\docs\\a.pdf", "C:\\docs\\b.pdf"],
  });
  assert.deepEqual(result.orderedInputPaths, ["C:\\docs\\a.pdf", "C:\\docs\\b.pdf"]);
  assert.equal(result.allowedPdfPaths.has("C:\\docs\\a.pdf"), true);
  assert.equal(result.allowedPdfPaths.has("C:\\docs\\b.pdf"), true);
}

// ケース3: 欠損PDF が1件（b.pdf が欠損）
// → b.pdf は allowedPdfPaths に残り、orderedInputPaths にも含まれる（退避方式の核心）
{
  const result = buildSaveStateFilter({
    loadedPdfPaths: ["C:\\docs\\a.pdf"],
    savedInputPaths: ["C:\\docs\\a.pdf", "C:\\docs\\b.pdf"],
  });
  assert.deepEqual(result.orderedInputPaths, ["C:\\docs\\a.pdf", "C:\\docs\\b.pdf"]);
  assert.equal(result.allowedPdfPaths.has("C:\\docs\\a.pdf"), true);
  assert.equal(result.allowedPdfPaths.has("C:\\docs\\b.pdf"), true, "欠損PDF b.pdf は allowedPdfPaths に残るべき");
}

// ケース4: 欠損PDF が複数（先頭・末尾）
// → 全欠損PDFが保護される
{
  const result = buildSaveStateFilter({
    loadedPdfPaths: ["C:\\docs\\b.pdf"],
    savedInputPaths: ["C:\\docs\\a.pdf", "C:\\docs\\b.pdf", "C:\\docs\\c.pdf"],
  });
  assert.deepEqual(result.orderedInputPaths, ["C:\\docs\\a.pdf", "C:\\docs\\b.pdf", "C:\\docs\\c.pdf"]);
  assert.equal(result.allowedPdfPaths.has("C:\\docs\\a.pdf"), true);
  assert.equal(result.allowedPdfPaths.has("C:\\docs\\b.pdf"), true);
  assert.equal(result.allowedPdfPaths.has("C:\\docs\\c.pdf"), true);
}

// ケース5: 全PDF欠損
// → orderedInputPaths には savedInputPaths の全パスが含まれる（ユーザーが再選択できるよう保持）
{
  const result = buildSaveStateFilter({
    loadedPdfPaths: [],
    savedInputPaths: ["C:\\docs\\a.pdf", "C:\\docs\\b.pdf"],
  });
  assert.deepEqual(result.orderedInputPaths, ["C:\\docs\\a.pdf", "C:\\docs\\b.pdf"]);
  assert.equal(result.allowedPdfPaths.has("C:\\docs\\a.pdf"), true);
  assert.equal(result.allowedPdfPaths.has("C:\\docs\\b.pdf"), true);
}

// ケース6: ユーザーが新規PDFを追加（savedInputPaths に未登録）
// → 新規追加分は orderedInputPaths の末尾に追加される
{
  const result = buildSaveStateFilter({
    loadedPdfPaths: ["C:\\docs\\a.pdf", "C:\\docs\\new.pdf"],
    savedInputPaths: ["C:\\docs\\a.pdf"],
  });
  assert.deepEqual(result.orderedInputPaths, ["C:\\docs\\a.pdf", "C:\\docs\\new.pdf"]);
  assert.equal(result.allowedPdfPaths.has("C:\\docs\\a.pdf"), true);
  assert.equal(result.allowedPdfPaths.has("C:\\docs\\new.pdf"), true);
}

// ケース7: 欠損PDF あり + 新規追加あり の複合ケース
// → savedInputPaths の順序 → 欠損PDF保護 → 新規追加が末尾
{
  const result = buildSaveStateFilter({
    loadedPdfPaths: ["C:\\docs\\a.pdf", "C:\\docs\\new.pdf"],
    savedInputPaths: ["C:\\docs\\a.pdf", "C:\\docs\\missing.pdf"],
  });
  assert.deepEqual(result.orderedInputPaths, ["C:\\docs\\a.pdf", "C:\\docs\\missing.pdf", "C:\\docs\\new.pdf"]);
  assert.equal(result.allowedPdfPaths.has("C:\\docs\\missing.pdf"), true, "欠損PDF は保護されるべき");
  assert.equal(result.allowedPdfPaths.has("C:\\docs\\new.pdf"), true);
}

// ケース8: savedInputPaths にないパスは allowedPdfPaths に含まれない（orphan 除外の維持）
// savedInputPaths 空で loadedPdfPaths にある場合は新規追加扱いで保存される
{
  const result = buildSaveStateFilter({
    loadedPdfPaths: ["C:\\docs\\a.pdf"],
    savedInputPaths: ["C:\\docs\\b.pdf"],  // b は欠損として保持、a は新規追加
  });
  // b は savedInputPaths にあるが pdfFiles にないので欠損保持
  assert.equal(result.allowedPdfPaths.has("C:\\docs\\b.pdf"), true);
  // a は savedInputPaths にないが loadedPdfPaths にあるので新規追加
  assert.equal(result.allowedPdfPaths.has("C:\\docs\\a.pdf"), true);
  assert.deepEqual(result.orderedInputPaths, ["C:\\docs\\b.pdf", "C:\\docs\\a.pdf"]);
}

// --- shouldRetainSegmentKey ---

// ケース9: 現在ロード中のセグメントキーは常に保存
{
  const currentSegmentKeys = new Set(["C:\\docs\\a.pdf#0"]);
  const allowedPdfPaths = new Set(["C:\\docs\\a.pdf"]);
  const loadedPdfPathSet = new Set(["C:\\docs\\a.pdf"]);

  assert.equal(
    shouldRetainSegmentKey("C:\\docs\\a.pdf#0", currentSegmentKeys, allowedPdfPaths, loadedPdfPathSet),
    true,
    "ロード中のセグメントは保存する"
  );
}

// ケース10: 欠損PDF配下のキーは allowedPdfPaths で保護される（退避の核心）
{
  const currentSegmentKeys = new Set(["C:\\docs\\a.pdf#0"]);
  const allowedPdfPaths = new Set(["C:\\docs\\a.pdf", "C:\\docs\\missing.pdf"]);
  const loadedPdfPathSet = new Set(["C:\\docs\\a.pdf"]);

  assert.equal(
    shouldRetainSegmentKey("C:\\docs\\missing.pdf#0", currentSegmentKeys, allowedPdfPaths, loadedPdfPathSet),
    true,
    "欠損PDF配下のキーは保存する"
  );
  assert.equal(
    shouldRetainSegmentKey("C:\\docs\\missing.pdf#1", currentSegmentKeys, allowedPdfPaths, loadedPdfPathSet),
    true,
    "欠損PDF配下の複数セグメントも保存する"
  );
}

// ケース11: savedInputPaths にもない真のorphan は除外される
{
  const currentSegmentKeys = new Set(["C:\\docs\\a.pdf#0"]);
  const allowedPdfPaths = new Set(["C:\\docs\\a.pdf"]);
  const loadedPdfPathSet = new Set(["C:\\docs\\a.pdf"]);

  assert.equal(
    shouldRetainSegmentKey("C:\\docs\\orphan.pdf#0", currentSegmentKeys, allowedPdfPaths, loadedPdfPathSet),
    false,
    "真のorphan（allowedPdfPaths にないPDF配下のキー）は除外する"
  );
}

// ケース12: manual_seq_keys の欠損PDF分も保護される（shouldRetainSegmentKey を共用）
{
  const currentSegmentKeys = new Set(["C:\\docs\\a.pdf#0"]);
  const allowedPdfPaths = new Set(["C:\\docs\\a.pdf", "C:\\docs\\missing.pdf"]);
  const loadedPdfPathSet = new Set(["C:\\docs\\a.pdf"]);

  // 欠損PDF の manual_seq_key は保護される
  assert.equal(
    shouldRetainSegmentKey("C:\\docs\\missing.pdf#2", currentSegmentKeys, allowedPdfPaths, loadedPdfPathSet),
    true
  );
  // 真のorphan の manual_seq_key は除外される
  assert.equal(
    shouldRetainSegmentKey("C:\\docs\\gone.pdf#0", currentSegmentKeys, allowedPdfPaths, loadedPdfPathSet),
    false
  );
}

console.log("[test:save-state] all assertions passed");

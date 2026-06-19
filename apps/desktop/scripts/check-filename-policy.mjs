import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const ts = require("typescript");

const __dirname = dirname(fileURLToPath(import.meta.url));
const sourcePath = join(__dirname, "..", "lib", "filename-policy.ts");
const source = readFileSync(sourcePath, "utf8");
const transpiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2022,
  },
});

const filenamePolicyModule = { exports: {} };
const compile = new Function("exports", "require", "module", "__filename", "__dirname", transpiled.outputText);
compile(filenamePolicyModule.exports, require, filenamePolicyModule, sourcePath, dirname(sourcePath));

const { missingMetadata, previewFilename, sanitizeFilename } = filenamePolicyModule.exports;

assert.equal(previewFilename({ box_no: "1", binder_no: "2", seq: "3" }), "01_02_003.pdf");
assert.equal(previewFilename({ box_no: "1/", binder_no: "2:", seq: "3*" }), "1__2__03_.pdf");
// 前後空白は trim してから 0 埋め（domain.py の strip と同一。" 1" でもプレビューと実出力が一致する）
assert.equal(previewFilename({ box_no: " 1", binder_no: "2 ", seq: " 3 " }), "01_02_003.pdf");
assert.deepEqual(missingMetadata({ box_no: "1", binder_no: "", seq: "3" }), ["binder_no"]);
assert.equal(previewFilename({ box_no: "1", binder_no: "", seq: "3" }), "未入力");
assert.equal(sanitizeFilename("bad:name* /file?.pdf"), "bad_name_ _file_.pdf");
assert.equal(sanitizeFilename("report.pdf. "), "report.pdf");
assert.equal(sanitizeFilename("...   "), "output.pdf");

// --- 追加項目(affix): 先頭/末尾への任意挿入。domain.py のビルダと論理同型であること ---
const companyPrefix = { key: "company", label: "会社名", position: "prefix" };
const docSuffix = { key: "doc", label: "契約書名", position: "suffix" };

assert.equal(
  previewFilename({ box_no: "1", binder_no: "2", seq: "3", company: "A商事", doc: "基本契約" }, [companyPrefix, docSuffix]),
  "A商事_01_02_003_基本契約.pdf"
);
// 空の追加項目は区切りごと詰める
assert.equal(
  previewFilename({ box_no: "1", binder_no: "2", seq: "3", company: "A商事" }, [companyPrefix, docSuffix]),
  "A商事_01_02_003.pdf"
);
// 両方空 → 従来テンプレートと完全一致（後方互換）
assert.equal(previewFilename({ box_no: "1", binder_no: "2", seq: "3" }, [companyPrefix, docSuffix]), "01_02_003.pdf");
// 同位置は定義順
assert.equal(
  previewFilename({ box_no: "1", binder_no: "2", seq: "3", company: "X", doc: "Y" }, [
    { key: "company", label: "会社名", position: "prefix" },
    { key: "doc", label: "契約書名", position: "prefix" }
  ]),
  "X_Y_01_02_003.pdf"
);
// 追加項目は必須判定に影響しない（固定3項目が欠ければ未入力）
assert.equal(previewFilename({ box_no: "1", binder_no: "", seq: "3", company: "A商事" }, [companyPrefix]), "未入力");

// --- 連番(seq)桁数の可変。domain.py の seq_digits と論理同型であること ---
assert.equal(previewFilename({ box_no: "1", binder_no: "2", seq: "3" }), "01_02_003.pdf"); // 既定3
assert.equal(previewFilename({ box_no: "1", binder_no: "2", seq: "3" }, [], 4), "01_02_0003.pdf");
assert.equal(previewFilename({ box_no: "1", binder_no: "2", seq: "3" }, [], 2), "01_02_03.pdf");
assert.equal(previewFilename({ box_no: "1", binder_no: "2", seq: "3" }, [], 0), "01_02_3.pdf"); // 下限1
assert.equal(
  previewFilename({ box_no: "1", binder_no: "2", seq: "3", company: "A商事" }, [companyPrefix], 4),
  "A商事_01_02_0003.pdf"
);

// --- #84: 制御文字・全角禁止文字・stem末尾ドット ---

// 制御文字 U+0000-U+001F → "_" に置換
assert.equal(sanitizeFilename("name\x00file.pdf"), "name_file.pdf");  // null byte
assert.equal(sanitizeFilename("name\nfile.pdf"), "name_file.pdf");    // newline
assert.equal(sanitizeFilename("name\rfile.pdf"), "name_file.pdf");    // carriage return
assert.equal(sanitizeFilename("name\tfile.pdf"), "name_file.pdf");    // tab
assert.equal(sanitizeFilename("name\x1efile.pdf"), "name_file.pdf"); // RS (0x1E)

// 全角禁止文字 → "_" に置換（日本語など意図した全角文字はそのまま）
assert.equal(sanitizeFilename("A商事＜＞.pdf"), "A商事__.pdf");   // ＜＞
assert.equal(sanitizeFilename("name：.pdf"), "name_.pdf");             // ：
assert.equal(sanitizeFilename("name＂.pdf"), "name_.pdf");             // ＂
assert.equal(sanitizeFilename("name／.pdf"), "name_.pdf");             // ／
assert.equal(sanitizeFilename("name＼.pdf"), "name_.pdf");             // ＼
assert.equal(sanitizeFilename("name｜.pdf"), "name_.pdf");             // ｜
assert.equal(sanitizeFilename("name？.pdf"), "name_.pdf");             // ？
assert.equal(sanitizeFilename("name＊.pdf"), "name_.pdf");             // ＊

// 全角禁止文字でない全角文字（全角英数・日本語）はそのまま
assert.equal(sanitizeFilename("日本語テスト_ＡＢＣ.pdf"), "日本語テスト_ＡＢＣ.pdf");

// stem末尾のドット/スペース除去（Windowsでstem末尾ドットは不正）
assert.equal(sanitizeFilename("name..pdf"), "name.pdf");        // stem trailing dot
assert.equal(sanitizeFilename("name. .pdf"), "name.pdf");       // stem trailing dot-space
assert.equal(sanitizeFilename("name   .pdf"), "name.pdf");      // stem trailing spaces
assert.equal(sanitizeFilename("report.pdf."), "report.pdf");    // trailing dot after ext
assert.equal(sanitizeFilename("report.pdf. "), "report.pdf");   // trailing space-dot after ext (already existed)

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
assert.equal(previewFilename({ box_no: " 1", binder_no: "2 ", seq: " 3 " }), "1_2 _ 3 .pdf");
assert.deepEqual(missingMetadata({ box_no: "1", binder_no: "", seq: "3" }), ["binder_no"]);
assert.equal(previewFilename({ box_no: "1", binder_no: "", seq: "3" }), "未入力");
assert.equal(sanitizeFilename("bad:name* /file?.pdf"), "bad_name_ _file_.pdf");
assert.equal(sanitizeFilename("report.pdf. "), "report.pdf");
assert.equal(sanitizeFilename("...   "), "output.pdf");

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const ts = require("typescript");

const __dirname = dirname(fileURLToPath(import.meta.url));
const sourcePath = join(__dirname, "..", "lib", "segment-state.ts");
const source = readFileSync(sourcePath, "utf8");
const transpiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2022,
  },
});

const segmentStateModule = { exports: {} };
const compile = new Function("exports", "require", "module", "__filename", "__dirname", transpiled.outputText);
compile(segmentStateModule.exports, require, segmentStateModule, sourcePath, dirname(sourcePath));

const {
  buildSegments,
  reconcileSegmentMetadataForPdf,
  segmentKey,
  splitPointsFor,
} = segmentStateModule.exports;

const pdfPath = "C:\\docs\\a.pdf";
const otherPdfPath = "C:\\docs\\b.pdf";
const wholeKey = segmentKey(pdfPath, 1, 10);
const firstSplitKey = segmentKey(pdfPath, 1, 5);
const secondSplitKey = segmentKey(pdfPath, 6, 10);
const otherPdfKey = segmentKey(otherPdfPath, 1, 3);

assert.deepEqual(splitPointsFor(5, [5, 2, 5, 1, 0, 6]), [2, 5]);

{
  const metadata = {
    [firstSplitKey]: { box_no: "01", binder_no: "02", seq: "001", note: "keep" },
    [secondSplitKey]: { box_no: "01", binder_no: "02", seq: "002" },
  };
  const reconciled = reconcileSegmentMetadataForPdf({
    pageCount: 10,
    pdfPath,
    previousSplitPoints: [6],
    nextSplitPoints: [6],
    segmentMetadata: metadata,
  });

  assert.deepEqual(reconciled[firstSplitKey], metadata[firstSplitKey]);
  assert.deepEqual(reconciled[secondSplitKey], metadata[secondSplitKey]);
}

{
  const reconciled = reconcileSegmentMetadataForPdf({
    pageCount: 10,
    pdfPath,
    previousSplitPoints: [],
    nextSplitPoints: [6],
    segmentMetadata: {
      [wholeKey]: { box_no: "09", binder_no: "12", seq: "007", custom: "old" },
      [otherPdfKey]: { box_no: "77", binder_no: "88", seq: "999" },
    },
  });

  assert.deepEqual(reconciled[firstSplitKey], { box_no: "09", binder_no: "12", seq: "" });
  assert.deepEqual(reconciled[secondSplitKey], { box_no: "09", binder_no: "12", seq: "" });
  assert.deepEqual(reconciled[otherPdfKey], { box_no: "77", binder_no: "88", seq: "999" });

  const segments = buildSegments([{ path: pdfPath, pageCount: 10 }], { [pdfPath]: [6] }, reconciled, {
    box_no: "",
    binder_no: "",
  });
  assert.deepEqual(
    segments.map((segment) => segment.metadata),
    [
      { box_no: "09", binder_no: "12", seq: "" },
      { box_no: "09", binder_no: "12", seq: "" },
    ],
  );
}

{
  const originalMetadata = { box_no: "03", binder_no: "04", seq: "011", note: "undo target" };
  const reconciled = reconcileSegmentMetadataForPdf({
    pageCount: 10,
    pdfPath,
    previousSplitPoints: [6],
    nextSplitPoints: [],
    segmentMetadata: {
      [wholeKey]: originalMetadata,
      [firstSplitKey]: { box_no: "03", binder_no: "04", seq: "" },
      [secondSplitKey]: { box_no: "03", binder_no: "04", seq: "" },
      [otherPdfKey]: { box_no: "77", binder_no: "88", seq: "999" },
    },
  });

  assert.deepEqual(reconciled[wholeKey], originalMetadata);
  assert.deepEqual(reconciled[otherPdfKey], { box_no: "77", binder_no: "88", seq: "999" });
}

{
  const noContainingSegmentKey = segmentKey(pdfPath, 1, 4);
  const reconciled = reconcileSegmentMetadataForPdf({
    pageCount: 10,
    pdfPath,
    previousSplitPoints: [5, 8],
    nextSplitPoints: [],
    segmentMetadata: {
      [noContainingSegmentKey]: { box_no: "01", binder_no: "02", seq: "001" },
    },
  });

  assert.equal(reconciled[wholeKey], undefined);
}

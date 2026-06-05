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
const otherPdfFirstSplitKey = segmentKey(otherPdfPath, 1, 1);
const otherPdfSecondSplitKey = segmentKey(otherPdfPath, 2, 3);

assert.deepEqual(splitPointsFor(5, [5, 2, 5, 1, 0, 6]), [2, 5]);

{
  const segments = buildSegments(
    [
      { path: otherPdfPath, pageCount: 3 },
      { path: pdfPath, pageCount: 10 },
    ],
    {
      [pdfPath]: [6],
      [otherPdfPath]: [2],
    },
    {
      [firstSplitKey]: { box_no: "segment-box", binder_no: "segment-binder", seq: "001" },
      [otherPdfSecondSplitKey]: { binder_no: "other-binder", seq: "002" },
    },
    {
      box_no: "common-box",
      binder_no: "common-binder",
    },
  );

  assert.deepEqual(
    segments.map((segment) => segment.key),
    [otherPdfFirstSplitKey, otherPdfSecondSplitKey, firstSplitKey, secondSplitKey],
  );
  assert.deepEqual(
    segments.map((segment) => segment.pages),
    ["1", "2-3", "1-5", "6-10"],
  );
  assert.deepEqual(segments[0].metadata, {
    box_no: "common-box",
    binder_no: "common-binder",
    seq: "",
  });
  assert.deepEqual(segments[1].metadata, {
    box_no: "common-box",
    binder_no: "other-binder",
    seq: "002",
  });
  assert.deepEqual(segments[2].metadata, {
    box_no: "segment-box",
    binder_no: "segment-binder",
    seq: "001",
  });
  assert.deepEqual(segments[3].metadata, {
    box_no: "common-box",
    binder_no: "common-binder",
    seq: "",
  });
}

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
  const splitPointsByPdf = {
    [pdfPath]: [],
    [otherPdfPath]: [2],
  };
  const reconciled = reconcileSegmentMetadataForPdf({
    pageCount: 10,
    pdfPath,
    previousSplitPoints: splitPointsByPdf[pdfPath],
    nextSplitPoints: [6],
    segmentMetadata: {
      [wholeKey]: { box_no: "09", binder_no: "12", seq: "007", custom: "old" },
      [otherPdfKey]: { box_no: "77", binder_no: "88", seq: "999" },
      [otherPdfFirstSplitKey]: { box_no: "55", binder_no: "66", seq: "111" },
    },
  });

  assert.deepEqual(reconciled[firstSplitKey], { box_no: "09", binder_no: "12", seq: "" });
  assert.deepEqual(reconciled[secondSplitKey], { box_no: "09", binder_no: "12", seq: "" });
  assert.deepEqual(reconciled[otherPdfKey], { box_no: "77", binder_no: "88", seq: "999" });
  assert.deepEqual(reconciled[otherPdfFirstSplitKey], { box_no: "55", binder_no: "66", seq: "111" });
  assert.deepEqual(splitPointsByPdf, {
    [pdfPath]: [],
    [otherPdfPath]: [2],
  });

  const segments = buildSegments(
    [
      { path: pdfPath, pageCount: 10 },
      { path: otherPdfPath, pageCount: 3 },
    ],
    { ...splitPointsByPdf, [pdfPath]: [6] },
    reconciled,
    {
      box_no: "",
      binder_no: "",
    },
  );
  assert.deepEqual(
    segments.map((segment) => segment.metadata),
    [
      { box_no: "09", binder_no: "12", seq: "" },
      { box_no: "09", binder_no: "12", seq: "" },
      { box_no: "55", binder_no: "66", seq: "111" },
      { box_no: "", binder_no: "", seq: "" },
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

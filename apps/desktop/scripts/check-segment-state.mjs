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
  resequenceSegmentMetadata,
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
const hashPdfPath = "C:\\docs\\a#draft.pdf";
const hashPdfKey = segmentKey(hashPdfPath, 1, 2);

assert.deepEqual(splitPointsFor(5, [5, 2, 5, 1, 0, 6]), [2, 5]);

{
  const segments = buildSegments(
    [
      { path: "C:\\docs\\empty.pdf", pageCount: 0 },
      { path: otherPdfPath, pageCount: 3 },
    ],
    {},
    {},
    { box_no: "01", binder_no: "02" },
  );

  assert.deepEqual(
    segments.map((segment) => segment.key),
    [otherPdfKey],
  );
  assert.equal(segments.some((segment) => segment.pages === "1-0"), false);
}

{
  const metadata = {
    [hashPdfKey]: { box_no: "hash-box", binder_no: "hash-binder", seq: "old-hash", note: "keep-hash" },
  };
  const segments = buildSegments(
    [{ path: hashPdfPath, pageCount: 2 }],
    {},
    metadata,
    {
      box_no: "common-box",
      binder_no: "common-binder",
    },
  );

  assert.deepEqual(
    segments.map((segment) => segment.key),
    [hashPdfKey],
  );
  assert.deepEqual(segments[0].metadata, {
    box_no: "hash-box",
    binder_no: "hash-binder",
    seq: "old-hash",
    note: "keep-hash",
  });

  const resequenced = resequenceSegmentMetadata(segments, metadata);

  assert.deepEqual(resequenced[hashPdfKey], {
    box_no: "hash-box",
    binder_no: "hash-binder",
    seq: "1",
    note: "keep-hash",
  });
  assert.deepEqual(metadata[hashPdfKey], {
    box_no: "hash-box",
    binder_no: "hash-binder",
    seq: "old-hash",
    note: "keep-hash",
  });
}

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
  const segments = buildSegments(
    [
      { path: otherPdfPath, pageCount: 3 },
      { path: pdfPath, pageCount: 10 },
    ],
    {
      [pdfPath]: [6],
      [otherPdfPath]: [2],
    },
    {},
    {
      box_no: "",
      binder_no: "",
    },
  );
  const metadata = {
    [firstSplitKey]: { box_no: "a-box", binder_no: "a-binder", seq: "old-a", custom: "keep-a" },
    [secondSplitKey]: { box_no: "b-box", binder_no: "b-binder", seq: "old-b" },
    [otherPdfFirstSplitKey]: { box_no: "other-box-1", binder_no: "other-binder-1", seq: "old-other-1" },
    [otherPdfSecondSplitKey]: { box_no: "other-box-2", binder_no: "other-binder-2", seq: "old-other-2", note: "keep-other" },
  };

  const resequenced = resequenceSegmentMetadata(segments, metadata);

  assert.deepEqual(resequenced[otherPdfFirstSplitKey], {
    box_no: "other-box-1",
    binder_no: "other-binder-1",
    seq: "1",
  });
  assert.deepEqual(resequenced[otherPdfSecondSplitKey], {
    box_no: "other-box-2",
    binder_no: "other-binder-2",
    seq: "2",
    note: "keep-other",
  });
  assert.deepEqual(resequenced[firstSplitKey], {
    box_no: "a-box",
    binder_no: "a-binder",
    seq: "3",
    custom: "keep-a",
  });
  assert.deepEqual(resequenced[secondSplitKey], {
    box_no: "b-box",
    binder_no: "b-binder",
    seq: "4",
  });
  assert.deepEqual(metadata[firstSplitKey], {
    box_no: "a-box",
    binder_no: "a-binder",
    seq: "old-a",
    custom: "keep-a",
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

  assert.deepEqual(reconciled[firstSplitKey], { box_no: "09", binder_no: "12", seq: "", custom: "old" });
  assert.deepEqual(reconciled[secondSplitKey], { box_no: "09", binder_no: "12", seq: "", custom: "old" });
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
      { box_no: "09", binder_no: "12", seq: "", custom: "old" },
      { box_no: "09", binder_no: "12", seq: "", custom: "old" },
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
  const wholeOtherPdfKey = segmentKey(otherPdfPath, 1, 3);
  const reconciled = reconcileSegmentMetadataForPdf({
    pageCount: 10,
    pdfPath,
    previousSplitPoints: [2, 3, 4, 5, 6, 7, 8, 9, 10],
    nextSplitPoints: [],
    segmentMetadata: {
      [wholeKey]: { box_no: "11", binder_no: "22", seq: "033", note: "restore whole" },
      [segmentKey(pdfPath, 1, 1)]: { box_no: "11", binder_no: "22", seq: "001" },
      [segmentKey(pdfPath, 2, 2)]: { box_no: "11", binder_no: "22", seq: "002" },
      [wholeOtherPdfKey]: { box_no: "77", binder_no: "88", seq: "999", note: "keep other pdf" },
    },
  });

  assert.deepEqual(reconciled[wholeKey], { box_no: "11", binder_no: "22", seq: "033", note: "restore whole" });
  assert.deepEqual(reconciled[wholeOtherPdfKey], {
    box_no: "77",
    binder_no: "88",
    seq: "999",
    note: "keep other pdf",
  });

  const segments = buildSegments(
    [
      { path: pdfPath, pageCount: 10 },
      { path: otherPdfPath, pageCount: 3 },
    ],
    { [pdfPath]: [], [otherPdfPath]: [] },
    reconciled,
    { box_no: "", binder_no: "" },
  );

  assert.deepEqual(
    segments.map((segment) => segment.pages),
    ["1-10", "1-3"],
  );
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

// regression: affix fields (affix1, affix2, ...) must be carried over when split points change
{
  const reconciled = reconcileSegmentMetadataForPdf({
    pageCount: 10,
    pdfPath,
    previousSplitPoints: [],
    nextSplitPoints: [6],
    segmentMetadata: {
      [wholeKey]: { box_no: "10", binder_no: "20", seq: "001", affix1: "prefix-A", affix2: "suffix-B" },
    },
  });

  // seq is reset; box_no/binder_no and affix fields are inherited from the containing segment
  assert.deepEqual(reconciled[firstSplitKey], {
    box_no: "10",
    binder_no: "20",
    seq: "",
    affix1: "prefix-A",
    affix2: "suffix-B",
  });
  assert.deepEqual(reconciled[secondSplitKey], {
    box_no: "10",
    binder_no: "20",
    seq: "",
    affix1: "prefix-A",
    affix2: "suffix-B",
  });
}

// regression: 自動採番(seq)だけ入った=box/binder未保持(共通値依存)の親を分割した時、
// 空の box_no/binder_no を書き込まず、buildSegments で共通項目が反映され続けること。
// （実機で「分割後はファイル名に箱/バインダーが入らず、一括適用を押すまでダメ」だった原因の修正）
{
  const reconciled = reconcileSegmentMetadataForPdf({
    pageCount: 10,
    pdfPath,
    previousSplitPoints: [],
    nextSplitPoints: [6],
    segmentMetadata: {
      [wholeKey]: { seq: "1" },
    },
  });

  // 空の box_no/binder_no キーを作らない（seq のリセットのみ）。
  assert.deepEqual(reconciled[firstSplitKey], { seq: "" });
  assert.deepEqual(reconciled[secondSplitKey], { seq: "" });

  // 共通項目を入れて buildSegments すると、分割後の全セグメントへ箱/バインダーが反映される。
  const segments = buildSegments(
    [{ path: pdfPath, pageCount: 10 }],
    { [pdfPath]: [6] },
    reconciled,
    { box_no: "5", binder_no: "3" },
  );
  assert.deepEqual(
    segments.map((segment) => ({ box_no: segment.metadata.box_no, binder_no: segment.metadata.binder_no })),
    [
      { box_no: "5", binder_no: "3" },
      { box_no: "5", binder_no: "3" },
    ],
  );
}

console.log("[test:segment-state] all assertions passed");

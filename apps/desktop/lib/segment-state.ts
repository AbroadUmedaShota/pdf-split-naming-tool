export type PdfFile = {
  path: string;
  pageCount: number;
};

export type SegmentMetadata = Record<string, Record<string, string>>;

export type SegmentView = {
  key: string;
  pdfPath: string;
  startPage: number;
  endPage: number;
  pages: string;
  metadata: Record<string, string>;
};

type SegmentRange = {
  key: string;
  pdfPath: string;
  startPage: number;
  endPage: number;
};

export function segmentKey(pdfPath: string, startPage: number, endPage: number): string {
  return `${pdfPath}#${startPage}-${endPage}`;
}

function pageLabel(startPage: number, endPage: number): string {
  return startPage === endPage ? `${startPage}` : `${startPage}-${endPage}`;
}

export function splitPointsFor(pageCount: number, splitPoints: number[] | undefined): number[] {
  return [...new Set(splitPoints ?? [])]
    .filter((page) => page > 1 && page <= pageCount)
    .sort((a, b) => a - b);
}

function segmentRangesFor(pdfPath: string, pageCount: number, splitPoints: number[] | undefined): SegmentRange[] {
  const points = splitPointsFor(pageCount, splitPoints);
  const starts = [1, ...points];
  const ends = [...points.map((point) => point - 1), pageCount];

  return starts.map((startPage, index) => {
    const endPage = ends[index];
    return {
      key: segmentKey(pdfPath, startPage, endPage),
      pdfPath,
      startPage,
      endPage
    };
  });
}

export function buildSegments(
  pdfFiles: PdfFile[],
  splitPointsByPdf: Record<string, number[]>,
  segmentMetadata: SegmentMetadata,
  commonMetadata: Record<string, string>
): SegmentView[] {
  return pdfFiles.flatMap((file) =>
    segmentRangesFor(file.path, file.pageCount, splitPointsByPdf[file.path]).map((segment) => ({
      ...segment,
      pages: pageLabel(segment.startPage, segment.endPage),
      metadata: {
        box_no: commonMetadata.box_no ?? "",
        binder_no: commonMetadata.binder_no ?? "",
        seq: "",
        ...(segmentMetadata[segment.key] ?? {})
      }
    }))
  );
}

export function reconcileSegmentMetadataForPdf({
  pageCount,
  pdfPath,
  previousSplitPoints,
  nextSplitPoints,
  segmentMetadata
}: {
  pageCount: number;
  pdfPath: string;
  previousSplitPoints: number[] | undefined;
  nextSplitPoints: number[] | undefined;
  segmentMetadata: SegmentMetadata;
}): SegmentMetadata {
  const previousSegments = segmentRangesFor(pdfPath, pageCount, previousSplitPoints);
  const nextSegments = segmentRangesFor(pdfPath, pageCount, nextSplitPoints);
  const nextMetadata: SegmentMetadata = { ...segmentMetadata };

  for (const nextSegment of nextSegments) {
    if (nextMetadata[nextSegment.key]) {
      continue;
    }

    const containingPreviousSegment = previousSegments.find(
      (previousSegment) =>
        previousSegment.startPage <= nextSegment.startPage && previousSegment.endPage >= nextSegment.endPage
    );
    const previousMetadata = containingPreviousSegment ? segmentMetadata[containingPreviousSegment.key] : undefined;

    if (previousMetadata) {
      nextMetadata[nextSegment.key] = {
        box_no: previousMetadata.box_no ?? "",
        binder_no: previousMetadata.binder_no ?? "",
        seq: ""
      };
    }
  }

  return nextMetadata;
}

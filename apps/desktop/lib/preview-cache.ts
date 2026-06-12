export type PreviewCacheEntry = {
  imageDataUrl: string;
  pageNo: number;
};

export type PreviewCache = {
  clear(): void;
  clearPdf(pdfPath: string): void;
  get(pdfPath: string, pageNo: number): PreviewCacheEntry | null;
  set(pdfPath: string, pageNo: number, entry: PreviewCacheEntry): void;
  size(): number;
};

export type PreviewRequestGate = {
  invalidate(): void;
  isCurrent(requestId: number): boolean;
  next(): number;
};

const DEFAULT_MAX_ENTRIES = 30;

export function previewCacheKey(pdfPath: string, pageNo: number): string {
  return JSON.stringify([pdfPath, pageNo]);
}

function cachedPdfPath(key: string): string | null {
  try {
    const [pdfPath] = JSON.parse(key) as [unknown, unknown];
    return typeof pdfPath === "string" ? pdfPath : null;
  } catch {
    return null;
  }
}

export function createPreviewCache(maxEntries = DEFAULT_MAX_ENTRIES): PreviewCache {
  const entries = new Map<string, PreviewCacheEntry>();
  const cappedMaxEntries = Math.max(1, maxEntries);

  function touch(key: string, entry: PreviewCacheEntry): void {
    entries.delete(key);
    entries.set(key, entry);
  }

  return {
    clear() {
      entries.clear();
    },
    clearPdf(pdfPath: string) {
      for (const key of entries.keys()) {
        if (cachedPdfPath(key) === pdfPath) {
          entries.delete(key);
        }
      }
    },
    get(pdfPath: string, pageNo: number) {
      const key = previewCacheKey(pdfPath, pageNo);
      const entry = entries.get(key);
      if (!entry) {
        return null;
      }
      touch(key, entry);
      return entry;
    },
    set(pdfPath: string, pageNo: number, entry: PreviewCacheEntry) {
      touch(previewCacheKey(pdfPath, pageNo), entry);
      while (entries.size > cappedMaxEntries) {
        const oldestKey = entries.keys().next().value;
        if (typeof oldestKey !== "string") {
          return;
        }
        entries.delete(oldestKey);
      }
    },
    size() {
      return entries.size;
    }
  };
}

export function createPreviewRequestGate(): PreviewRequestGate {
  let currentRequestId = 0;

  return {
    invalidate() {
      currentRequestId += 1;
    },
    isCurrent(requestId: number) {
      return currentRequestId === requestId;
    },
    next() {
      currentRequestId += 1;
      return currentRequestId;
    }
  };
}

export const previewCache = createPreviewCache();

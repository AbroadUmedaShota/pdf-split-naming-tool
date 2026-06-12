export type RestorablePdfInfo = {
  path: string;
  pageCount: number;
};

export type MissingPdfStatusInput = {
  allMissing: boolean;
  paths: string[];
};

export type MissingSavedPdfRestoreInput = {
  currentPage?: number;
  currentPdf?: string;
  hasMissingInputPdf: boolean;
  loadedPdfFiles: RestorablePdfInfo[];
  missingInputPaths: string[];
  savedInputPaths: string[];
};

export type MissingSavedPdfRestoreDecision = {
  currentPage: number;
  currentPdf: string;
  missingStatusInput: MissingPdfStatusInput | null;
  restorableInputPaths: string[];
  shouldLoadPreview: boolean;
  statusText: string;
};

function basename(path: string): string {
  return path.split(/[\\/]/).filter(Boolean).pop() ?? path;
}

export function missingPdfStatus({ allMissing, paths }: MissingPdfStatusInput): string {
  const names = paths.slice(0, 2).map(basename).join("、");
  const suffix = paths.length > 2 ? ` ほか${paths.length - 2}件` : "";
  const target = names ? `（${names}${suffix}）` : "";
  // 保存時は現在のPDF構成でフィルタされるため、欠損PDF分の入力値は保存し直すと消える。
  const lossWarning = "このまま保存すると読み込めなかったPDFの入力値は失われます。";
  return allMissing
    ? `保存済みPDFが見つかりません${target}。再選択してください。${lossWarning}`
    : `一部の保存済みPDFが見つかりません${target}。再選択してください。${lossWarning}`;
}

export function restorableInputPaths(savedInputPaths: string[], missingInputPaths: string[]): string[] {
  const missing = new Set(missingInputPaths);
  return savedInputPaths.filter((path) => !missing.has(path));
}

export function resolveMissingSavedPdfRestore({
  currentPage,
  currentPdf,
  hasMissingInputPdf,
  loadedPdfFiles,
  missingInputPaths,
  savedInputPaths
}: MissingSavedPdfRestoreInput): MissingSavedPdfRestoreDecision {
  const restorablePaths = restorableInputPaths(savedInputPaths, missingInputPaths);
  const firstLoadedPdf = loadedPdfFiles[0];

  if (!firstLoadedPdf) {
    const missingStatusInput = hasMissingInputPdf
      ? {
          allMissing: true,
          paths: missingInputPaths
        }
      : null;
    return {
      currentPage: 1,
      currentPdf: "",
      missingStatusInput,
      restorableInputPaths: restorablePaths,
      shouldLoadPreview: false,
      statusText: missingStatusInput ? missingPdfStatus(missingStatusInput) : "保存済み状態はありません。"
    };
  }

  const loadedPdfByPath = new Map(loadedPdfFiles.map((file) => [file.path, file]));
  const firstRestorablePdf = restorablePaths.find((path) => loadedPdfByPath.has(path)) ?? firstLoadedPdf.path;
  const restoredPdf = loadedPdfByPath.has(currentPdf ?? "") ? currentPdf || firstRestorablePdf : firstRestorablePdf;
  const restoredFile = loadedPdfFiles.find((file) => file.path === restoredPdf) ?? firstLoadedPdf;
  const restoredPage = Math.min(Math.max(currentPage ?? 1, 1), restoredFile.pageCount);
  const missingStatusInput = hasMissingInputPdf
    ? {
        allMissing: false,
        paths: missingInputPaths
      }
    : null;

  return {
    currentPage: restoredPage,
    currentPdf: restoredPdf,
    missingStatusInput,
    restorableInputPaths: restorablePaths,
    shouldLoadPreview: true,
    statusText: missingStatusInput ? missingPdfStatus(missingStatusInput) : "状態を復元しました。"
  };
}

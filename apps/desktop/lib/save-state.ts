/**
 * saveState で使うフィルタロジック。
 *
 * 保存フィルタの基準を「現在ロード中のPDF」から
 * 「input_paths に残っている（savedInputPaths に含まれる）PDF」へ変更し、
 * 欠損中でも savedInputPaths に含まれるPDFのメタデータを保存する。
 * これによりPDFを元に戻して再読込すれば値が復活する。
 */

export type SaveStateFilterInput = {
  /** 現在ロード中のPDFパス一覧 */
  loadedPdfPaths: string[];
  /**
   * loadState で読み込んだ完全な入力パスリスト（欠損中のパスを含む）。
   * セッション開始時は空配列（loadState 未実行）。
   */
  savedInputPaths: string[];
};

export type SaveStateFilterResult = {
  /**
   * segment_metadata / split_points_by_pdf のフィルタ基準となるPDFパスのセット。
   * ロード済み + 欠損保持分を含む。
   */
  allowedPdfPaths: Set<string>;
  /**
   * input_paths として保存するパスの順序付き配列。
   * savedInputPaths の順序を維持しつつ、新規追加分を後ろへ追加する。
   */
  orderedInputPaths: string[];
};

/**
 * saveState のフィルタ基準を計算する。
 *
 * - 欠損中でも savedInputPaths に含まれるPDFは allowedPdfPaths に残す
 * - savedInputPaths に存在しないキー（真のorphan）は従来通り除外される
 * - ユーザーが新規追加したPDF（savedInputPaths 未登録）は orderedInputPaths の末尾に追加
 */
export function buildSaveStateFilter({
  loadedPdfPaths,
  savedInputPaths,
}: SaveStateFilterInput): SaveStateFilterResult {
  const loadedPdfPathSet = new Set(loadedPdfPaths);
  const savedPathSet = new Set(savedInputPaths);

  // 欠損中でも保持すべきパス（savedInputPaths に含まれるが現在 pdfFiles にないもの）
  const retainedMissingPaths = savedInputPaths.filter((p) => !loadedPdfPathSet.has(p));

  // 保存するPDFパスのセット（ロード済み + 欠損保持分）
  const allowedPdfPaths = new Set([...loadedPdfPathSet, ...retainedMissingPaths]);

  // input_paths: savedInputPaths の順を維持しつつ、新規追加分（savedInputPaths 未登録）を後ろへ
  const newlyAddedPaths = loadedPdfPaths.filter((p) => !savedPathSet.has(p));
  const orderedInputPaths = [
    ...savedInputPaths.filter((p) => allowedPdfPaths.has(p)),
    ...newlyAddedPaths,
  ];

  return { allowedPdfPaths, orderedInputPaths };
}

/**
 * segment_metadata のキーが保存対象かどうかを判定する。
 *
 * @param key segment_metadata のキー（形式: "pdfPath#segmentId"）
 * @param currentSegmentKeys 現在ロード中のセグメントキーのセット
 * @param allowedPdfPaths 保存対象PDFパスのセット
 * @param loadedPdfPathSet 現在ロード中のPDFパスのセット
 */
export function shouldRetainSegmentKey(
  key: string,
  currentSegmentKeys: Set<string>,
  allowedPdfPaths: Set<string>,
  loadedPdfPathSet: Set<string>,
): boolean {
  // 現在ロード中のセグメントは常に保存する
  if (currentSegmentKeys.has(key)) return true;
  // 欠損中のPDF配下のキーは allowedPdfPaths で保護する
  const pdfPath = key.split("#")[0];
  return allowedPdfPaths.has(pdfPath) && !loadedPdfPathSet.has(pdfPath);
}

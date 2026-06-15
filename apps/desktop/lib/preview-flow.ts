import type { PreviewCache, PreviewCacheEntry, PreviewRequestGate } from "./preview-cache";

export type PreviewFlowRequest = {
  command: "page_preview";
  pdf_path: string;
  page_no: number;
  zoom?: number;
};

export type PreviewFlowResponse = {
  ok: boolean;
  command: string;
  error?: string;
  image_data_url?: string;
  page_count?: number;
  page_no?: number;
};

export type PreviewFlowResult = "cache" | "sidecar" | "stale";

export type LoadPagePreviewOptions = {
  applyPreview(preview: PreviewCacheEntry): void;
  cache: PreviewCache;
  gate: PreviewRequestGate;
  invalidPreviewMessage?: string;
  pageNo: number;
  pdfPath: string;
  requestPreview(request: PreviewFlowRequest): Promise<PreviewFlowResponse>;
  responseErrorMessage?(response: PreviewFlowResponse): string;
  zoom?: number;
};

// サイドカー(pdf_service.py)は page_preview を軽量化のため JPEG で返す。PNG も将来互換で許容する。
// ブラウザはどちらの data URL も描画できるため、形式は限定せず「想定プレフィックス＋本体あり」だけ検証する。
const previewImageDataUrlPrefixes = ["data:image/jpeg;base64,", "data:image/png;base64,"];

// プレビュー/サムネイル共通の data URL 検証。サイドカーの返す画像形式(現状JPEG)に
// フロント側の想定がズレると全画像が表示されなくなる過去の不具合を、両経路で同じ判定に
// 寄せて再発防止する。export して page_thumbnail 取得側からも使う。
export function hasPreviewImageData(value: string): boolean {
  return previewImageDataUrlPrefixes.some(
    (prefix) => value.startsWith(prefix) && value.length > prefix.length
  );
}

function isValidPagePreviewResponse(
  response: PreviewFlowResponse,
  expectedPageNo: number
): response is PreviewFlowResponse & { image_data_url: string; page_count: number; page_no: number } {
  return (
    typeof response.image_data_url === "string" &&
    hasPreviewImageData(response.image_data_url) &&
    typeof response.page_count === "number" &&
    Number.isInteger(response.page_count) &&
    response.page_count > 0 &&
    typeof response.page_no === "number" &&
    Number.isInteger(response.page_no) &&
    response.page_no > 0 &&
    response.page_no === expectedPageNo &&
    response.page_no <= response.page_count
  );
}

export async function loadPagePreview({
  applyPreview,
  cache,
  gate,
  invalidPreviewMessage = "Preview response was not a page preview.",
  pageNo,
  pdfPath,
  requestPreview,
  responseErrorMessage = (response) => response.error ?? "Preview response was not usable.",
  zoom
}: LoadPagePreviewOptions): Promise<PreviewFlowResult> {
  const requestId = gate.next();
  const cachedPreview = cache.get(pdfPath, pageNo);
  if (cachedPreview) {
    applyPreview(cachedPreview);
    return "cache";
  }

  const request: PreviewFlowRequest = { command: "page_preview", pdf_path: pdfPath, page_no: pageNo };
  if (typeof zoom === "number") {
    request.zoom = zoom;
  }
  const response = await requestPreview(request);
  if (!gate.isCurrent(requestId)) {
    return "stale";
  }
  if (!response.ok || response.command !== "page_preview") {
    throw new Error(response.ok ? invalidPreviewMessage : responseErrorMessage(response));
  }
  if (!isValidPagePreviewResponse(response, pageNo)) {
    throw new Error(invalidPreviewMessage);
  }

  const preview = {
    imageDataUrl: response.image_data_url,
    pageNo: response.page_no
  };
  cache.set(pdfPath, pageNo, preview);
  applyPreview(preview);
  return "sidecar";
}

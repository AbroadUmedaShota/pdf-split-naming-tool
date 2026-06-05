import type { PreviewCache, PreviewCacheEntry, PreviewRequestGate } from "./preview-cache";

export type PreviewFlowRequest = {
  command: "page_preview";
  pdf_path: string;
  page_no: number;
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
};

const previewImageDataUrlPrefix = "data:image/png;base64,";

function isValidPagePreviewResponse(
  response: PreviewFlowResponse,
  expectedPageNo: number
): response is PreviewFlowResponse & { image_data_url: string; page_count: number; page_no: number } {
  return (
    typeof response.image_data_url === "string" &&
    response.image_data_url.startsWith(previewImageDataUrlPrefix) &&
    response.image_data_url.length > previewImageDataUrlPrefix.length &&
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
  responseErrorMessage = (response) => response.error ?? "Preview response was not usable."
}: LoadPagePreviewOptions): Promise<PreviewFlowResult> {
  const requestId = gate.next();
  const cachedPreview = cache.get(pdfPath, pageNo);
  if (cachedPreview) {
    applyPreview(cachedPreview);
    return "cache";
  }

  const response = await requestPreview({ command: "page_preview", pdf_path: pdfPath, page_no: pageNo });
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

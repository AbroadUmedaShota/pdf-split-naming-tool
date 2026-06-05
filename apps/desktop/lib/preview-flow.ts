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

  const previewResponse = response as { image_data_url: string; page_no: number };
  const preview = {
    imageDataUrl: previewResponse.image_data_url,
    pageNo: previewResponse.page_no
  };
  cache.set(pdfPath, pageNo, preview);
  applyPreview(preview);
  return "sidecar";
}

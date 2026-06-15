import { invoke } from "@tauri-apps/api/core";

export const SIDE_CAR_COMMANDS = [
  "pdf_info",
  "page_preview",
  "page_thumbnail",
  "page_text",
  "search_text",
  "search_highlights",
  "index_candidates",
  "blank_candidates",
  "preflight",
  "export",
  "state_load",
  "state_save"
] as const;

export type SidecarCommand = (typeof SIDE_CAR_COMMANDS)[number];

export async function invokeSidecar(request: SidecarRequest): Promise<SidecarResponse> {
  return invoke<SidecarResponse>("run_sidecar", { request });
}

// 出力先フォルダを OS のファイルマネージャで開く。出力後に生成PDFを確認する後工程への導線。
export async function revealPath(path: string): Promise<void> {
  await invoke<void>("reveal_path", { path });
}

export type AppAffixDef = {
  key: string;
  label: string;
  position: "prefix" | "suffix";
};

export type AppPersistedState = {
  version: 1;
  input_paths: string[];
  output_dir: string;
  split_points_by_pdf: Record<string, number[]>;
  segment_metadata: Record<string, Record<string, string>>;
  common_metadata: Record<string, string>;
  affix_defs: AppAffixDef[];
  seq_start: number;
  seq_digits: number;
  manual_seq_keys: string[];
  current_pdf: string;
  current_page: number;
  active_step?: "import" | "split" | "input" | "output";
};

export type SidecarRequest =
  | { command: "pdf_info"; pdf_path: string }
  | { command: "page_preview"; pdf_path: string; page_no: number; zoom?: number }
  | { command: "page_thumbnail"; pdf_path: string; page_no: number; zoom?: number }
  | { command: "page_text"; pdf_path: string; page_no: number }
  // search_text: queries で複数用語を1リクエストにまとめる（query は旧形式との互換用）。
  | { command: "search_text"; pdf_paths: string[]; queries: string[]; query?: string; scope?: SearchScope; current_pdf?: string }
  | { command: "search_highlights"; pdf_path: string; page_no: number; query: string }
  | { command: "index_candidates"; pdf_paths: string[]; keywords?: string[] }
  // blank_candidates: start_page から走査を再開できる（時間予算打ち切り時の継続取得用）。
  | { command: "blank_candidates"; pdf_path: string; threshold?: number; start_page?: number }
  | SidecarPreflightRequest
  | SidecarExportRequest
  | { command: "state_load"; work_dir?: string }
  | { command: "state_save"; work_dir?: string; state: AppPersistedState };

export type SidecarPreflightRequest = {
  command: "preflight";
  output_dir: string;
  segments: SidecarSegment[];
  affix_defs?: AppAffixDef[];
  seq_digits?: number;
};

export type SidecarExportRequest = {
  command: "export";
  output_dir: string;
  segments: SidecarSegment[];
  affix_defs?: AppAffixDef[];
  seq_digits?: number;
};

export type SidecarResponse =
  | SidecarErrorResponse
  | SidecarPdfInfoResponse
  | SidecarPreviewResponse
  | SidecarThumbnailResponse
  | SidecarPageTextResponse
  | SidecarSearchTextResponse
  | SidecarSearchHighlightsResponse
  | SidecarIndexCandidatesResponse
  | SidecarBlankCandidatesResponse
  | SidecarPreflightResponse
  | SidecarExportResponse
  | SidecarStateLoadResponse
  | SidecarStateSaveResponse;

export type SidecarErrorResponse = {
  ok: false;
  command: string;
  error: string;
  error_type: string;
};

export type SidecarPdfInfoResponse = {
  ok: true;
  command: "pdf_info";
  pdf_path: string;
  page_count: number;
  naming_template: string;
};

export type SidecarPreviewResponse = {
  ok: true;
  command: "page_preview";
  pdf_path: string;
  page_no: number;
  page_count: number;
  image_data_url: string;
};

export type SidecarThumbnailResponse = {
  ok: true;
  command: "page_thumbnail";
  pdf_path: string;
  page_no: number;
  page_count: number;
  image_data_url: string;
};

export type SidecarPageTextResponse = {
  ok: true;
  command: "page_text";
  pdf_path: string;
  page_no: number;
  page_count: number;
  text: string;
  has_text: boolean;
};

export type SidecarSearchTextResponse = {
  ok: true;
  command: "search_text";
  query?: string;
  scope?: SearchScope;
  results: SidecarSearchResult[];
  // 結果件数の上限（200件）で打ち切られた場合 true。
  truncated?: boolean;
};

export type SearchScope = "current_pdf" | "all_pdfs";

export type SidecarSearchResult = {
  pdf_path: string;
  page_no: number;
  count: number;
  snippet: string;
  matched_terms?: string[];
  has_text?: boolean;
  is_current_pdf?: boolean;
};

export type SidecarSearchHighlightsResponse = {
  ok: true;
  command: "search_highlights";
  pdf_path: string;
  page_no: number;
  query: string;
  rects: SidecarSearchHighlightRect[];
};

export type SidecarSearchHighlightRect = {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  page_width: number;
  page_height: number;
};

export type SidecarIndexCandidatesResponse = {
  ok: true;
  command: "index_candidates";
  candidates: SidecarIndexCandidate[];
};

export type SidecarIndexCandidate = {
  pdf_path: string;
  page_no: number;
  score: number;
  reason: string;
  snippet: string;
};

export type SidecarBlankCandidatesResponse = {
  ok: true;
  command: "blank_candidates";
  pdf_path: string;
  threshold: number;
  candidates: SidecarBlankCandidate[];
  // 時間予算（約8秒）で走査が打ち切られた場合 true。scanned_until まで走査済み。
  partial?: boolean;
  scanned_until?: number;
};

export type SidecarBlankCandidate = {
  page_no: number;
  score: number;
};

export type SidecarPreflightResponse = {
  ok: boolean;
  command: "preflight";
  can_run: boolean;
  output_dir: string;
  messages: string[];
  checks: SidecarOutputCheck[];
};

export type SidecarExportResponse = {
  ok: boolean;
  command: "export";
  output_dir: string;
  summary: SidecarExportSummary;
  items: SidecarOutputItem[];
  messages?: string[];
};

export type SidecarStateLoadResponse = {
  ok: true;
  command: "state_load";
  work_dir: string;
  state: AppPersistedState | Record<string, never>;
  messages?: string[];
  missing_input_paths?: string[];
};

export type SidecarStateSaveResponse = {
  ok: true;
  command: "state_save";
  work_dir: string;
};

export type SidecarOutputStatus = "created" | "failed";

export type SidecarExportSummary = {
  created: number;
  failed: number;
};

export type SidecarOutputCheck = {
  ok: boolean;
  filename: string;
  output_path: string;
  messages: string[];
  requested_filename: string;
  requested_path: string;
  existing_path: string;
  has_existing_output: boolean;
  metadata: Record<string, string>;
  pages: string;
  pdf_path: string;
};

export type SidecarOutputItem = SidecarOutputCheck & {
  status: SidecarOutputStatus;
  sha256?: string;
  error?: string;
  error_type?: string;
};

export type SidecarSegment = {
  pdf_path: string;
  start_page: number;
  end_page: number;
  metadata?: Record<string, string>;
};

import { invoke } from "@tauri-apps/api/core";

export const SIDE_CAR_COMMANDS = [
  "pdf_info",
  "page_preview",
  "preflight",
  "export",
  "state_load",
  "state_save"
] as const;

export type SidecarCommand = (typeof SIDE_CAR_COMMANDS)[number];

export async function invokeSidecar(request: SidecarRequest): Promise<SidecarResponse> {
  return invoke<SidecarResponse>("run_sidecar", { request });
}

export type AppPersistedState = {
  version: 1;
  input_paths: string[];
  output_dir: string;
  split_points_by_pdf: Record<string, number[]>;
  segment_metadata: Record<string, Record<string, string>>;
  common_metadata: Record<string, string>;
  current_pdf: string;
  current_page: number;
  active_step?: "import" | "split" | "input" | "output";
};

export type SidecarRequest =
  | { command: "pdf_info"; pdf_path: string }
  | { command: "page_preview"; pdf_path: string; page_no: number }
  | SidecarPreflightRequest
  | SidecarExportRequest
  | { command: "state_load"; work_dir?: string }
  | { command: "state_save"; work_dir?: string; state: AppPersistedState };

export type SidecarPreflightRequest = {
  command: "preflight";
  output_dir: string;
  segments: SidecarSegment[];
};

export type SidecarExportRequest = {
  command: "export";
  output_dir: string;
  segments: SidecarSegment[];
};

export type SidecarResponse =
  | SidecarErrorResponse
  | SidecarPdfInfoResponse
  | SidecarPreviewResponse
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

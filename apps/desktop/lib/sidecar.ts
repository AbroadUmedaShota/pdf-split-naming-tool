import { invoke } from "@tauri-apps/api/core";

export const SIDE_CAR_COMMANDS = [
  "pdf_info",
  "page_text",
  "presets",
  "history",
  "preflight",
  "export"
] as const;

export type SidecarCommand = (typeof SIDE_CAR_COMMANDS)[number];

export async function invokeSidecar(request: SidecarRequest): Promise<SidecarResponse> {
  return invoke<SidecarResponse>("run_sidecar", { request });
}

export type SidecarOutputAction = "create_unique" | "reuse_existing" | "skip";

export type SidecarRequest =
  | { command: "pdf_info"; pdf_path: string }
  | { command: "page_text"; pdf_path: string; page_no: number; suggestion_limit?: number }
  | { command: "presets"; work_dir: string }
  | { command: "history"; work_dir: string }
  | SidecarPreflightRequest
  | SidecarExportRequest;

export type SidecarPreflightRequest = {
  command: "preflight";
  output_dir: string;
  work_dir?: string;
  segments: SidecarSegment[];
  preset?: SidecarPreset;
  output_actions?: Record<string, SidecarOutputAction>;
};

export type SidecarExportRequest = {
  command: "export";
  output_dir: string;
  work_dir?: string;
  segments: SidecarSegment[];
  preset?: SidecarPreset;
  output_actions?: Record<string, SidecarOutputAction>;
};

export type SidecarResponse =
  | SidecarErrorResponse
  | SidecarPdfInfoResponse
  | SidecarPageTextResponse
  | SidecarPresetsResponse
  | SidecarHistoryResponse
  | SidecarPreflightResponse
  | SidecarExportResponse;

export type SidecarError = {
  error: string;
  error_type: string;
};

export type SidecarErrorResponse = SidecarError & {
  ok: false;
  command: string;
};

export type SidecarPdfInfoResponse = {
  ok: true;
  command: "pdf_info";
  pdf_path: string;
  page_count: number;
  page_numbers: number[];
  has_text_layer: boolean;
  default_preset: SidecarPreset;
};

export type SidecarPageTextResponse = {
  ok: true;
  command: "page_text";
  pdf_path: string;
  page_no: number;
  text: string;
  suggestions: string[];
};

export type SidecarPresetsResponse = {
  ok: true;
  command: "presets";
  work_dir: string;
  active_preset_id: string;
  presets: SidecarPreset[];
};

export type SidecarHistoryResponse = {
  ok: true;
  command: "history";
  work_dir: string;
  count: number;
  runs: SidecarHistoryRun[];
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
  history: SidecarHistoryRun | null;
  history_error: SidecarError | null;
};

export type SidecarOutputStatus = "created" | "reused" | "skipped" | "failed";

export type SidecarExportSummary = {
  created: number;
  reused: number;
  skipped: number;
  failed: number;
};

export type SidecarHistoryRun = {
  version: number;
  created_at: string;
  summary: Record<string, unknown>;
  items: SidecarHistoryItem[];
};

export type SidecarHistoryItem = {
  status: SidecarOutputStatus | string;
  source_pdf?: string;
  pages?: string;
  requested_filename?: string;
  output_path?: string;
  sha256?: string;
  warnings?: string[];
  error?: string;
  error_type?: string;
};

export type SidecarOutputCheck = {
  ok: boolean;
  filename: string;
  output_path: string;
  messages: string[];
  action: SidecarOutputAction;
  requested_filename: string;
  requested_path: string;
  existing_path: string;
  has_existing_output: boolean;
  action_key: string;
  metadata: Record<string, string>;
  page_plan: SidecarPagePlan;
};

export type SidecarOutputItem = SidecarOutputCheck & SidecarHistoryItem & {
  status: SidecarOutputStatus;
  sha256?: string;
  error?: string;
  error_type?: string;
};

export type SidecarPagePlan = {
  source_pdf: string;
  pages: string;
  page_numbers: number[];
  rotations: Record<string, number>;
};

export type SidecarSegment = {
  pdf_path: string;
  start_page: number;
  end_page: number;
  metadata?: Record<string, string>;
  page_numbers?: number[];
  rotations?: Record<string, number>;
};

export type SidecarPreset = {
  id: string;
  name: string;
  fields: Array<{
    key: string;
    label: string;
    required: boolean;
    input_type?: string;
    default?: string;
  }>;
  naming_template: string;
  extraction_keywords?: string[];
  blank_threshold?: number;
  index_threshold?: number;
};

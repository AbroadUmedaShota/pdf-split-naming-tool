"use client";

import { desktopDir } from "@tauri-apps/api/path";
import { open } from "@tauri-apps/plugin-dialog";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  ChevronRight,
  ClipboardCheck,
  Copy,
  Download,
  FileText,
  FolderOpen,
  ListChecks,
  PencilLine,
  Plus,
  RefreshCw,
  RotateCcw,
  Save,
  Split,
  Trash2,
  Undo2,
  Upload,
  XCircle,
  type LucideIcon
} from "lucide-react";
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import {
  invokeSidecar,
  type AppPersistedState,
  type SidecarBlankCandidate,
  type SidecarExportResponse,
  type SidecarOutputCheck,
  type SidecarPageTextResponse,
  type SidecarPdfInfoResponse,
  type SidecarPreflightResponse,
  type SidecarResponse,
  type SidecarIndexCandidate,
  type SidecarIndexCandidatesResponse,
  type SidecarSearchHighlightRect,
  type SidecarSearchHighlightsResponse,
  type SidecarSearchResult,
  type SidecarSearchTextResponse,
  type SidecarSegment
} from "../lib/sidecar";
import { resolveMissingSavedPdfRestore, restorableInputPaths } from "../lib/restore-state";
import {
  AFFIX_POSITIONS,
  type AffixDef,
  DEFAULT_SEQ_DIGITS,
  MAX_AFFIX_COUNT,
  MAX_SEQ_DIGITS,
  MIN_SEQ_DIGITS,
  coerceSeqDigits,
  missingMetadata,
  previewFilename
} from "../lib/filename-policy";
import { formatTopLevelMessage, isOutputCheckOk, outputDetailStateText, outputIssueCount, outputListStateText } from "../lib/output-state";
import { loadPagePreview } from "../lib/preview-flow";
import { createPreviewRequestGate, previewCache } from "../lib/preview-cache";
import {
  buildSegments,
  reconcileSegmentMetadataForPdf,
  splitPointsFor,
  type PdfFile,
  type SegmentMetadata,
  type SegmentView
} from "../lib/segment-state";
import {
  checkForAppUpdate,
  installAppUpdate,
  readCurrentVersion,
  updateErrorMessage,
  type AppUpdate
} from "../lib/updates";

type StepId = "import" | "split" | "input" | "output";
type DevPreviewStep = StepId;

type StepState = "active" | "done" | "attention" | "idle";
type UpdateState = "idle" | "checking" | "current" | "available" | "installing" | "installed" | "error";
type PreviewFitMode = "free" | "width" | "page";
type SplitHistoryEntry = { pdfPath: string; points: number[] };
type SearchHighlightRect = SidecarSearchHighlightRect;
type IndexCandidate = SidecarIndexCandidate;
type SearchTermSource = "built_in" | "custom";
type SearchTermPreset = {
  customTerms: string[];
  selectedTerms: string[];
};
type SelectedSearchTerm = {
  source: SearchTermSource;
  term: string;
};
type MergedSearchResult = {
  matchedTerms: string[];
  pageNo: number;
  pdfPath: string;
  snippets: string[];
  totalCount: number;
};
type TermSearchHighlightRect = SearchHighlightRect & {
  term: string;
};
type SelectedSearchHit = {
  index: number;
  pageNo: number;
  pdfPath: string;
};
type PageState = {
  blankScore?: number;
  hasSplitBefore: boolean;
  isCurrent: boolean;
  pageNo: number;
  segment: SegmentView | null;
  thumbnail?: string;
};

const steps: Array<{ id: StepId; label: string; hint: string; icon: LucideIcon }> = [
  { id: "import", label: "PDF取込", hint: "PDF / 出力先", icon: FileText },
  { id: "split", label: "分割", hint: "ページ範囲", icon: Split },
  { id: "input", label: "入力", hint: "箱No / 連番", icon: PencilLine },
  { id: "output", label: "出力", hint: "チェック / 実行", icon: Download }
];

const defaultCommonMetadata = { box_no: "1", binder_no: "1" };
const SEARCH_TERM_PRESET_STORAGE_KEY = "pdf-organizer.step2SearchTerms.v1";
const CONTRACT_SEARCH_TERMS = [
  "契約書",
  "契約",
  "覚書",
  "注文書",
  "発注書",
  "請求書",
  "見積書",
  "納品書",
  "検収書",
  "申込書",
  "重要事項",
  "利用規約",
  "会社名",
  "書類名",
  "No.",
  "番号"
];
const defaultSelectedSearchTerms = ["契約書", "請求書"];
const step2ReviewPdfPath = "C:\\Users\\admin\\Downloads\\000高精度ocrのテスト用ファイル_searchable.pdf";
const step2ReviewPreviewDataUrl =
  "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 840 1188'%3E%3Crect width='840' height='1188' fill='%23f8f1e4'/%3E%3Crect x='88' y='132' width='664' height='924' fill='%23fffdf7' stroke='%238a8274' stroke-width='3'/%3E%3Ctext x='420' y='188' text-anchor='middle' font-family='Arial' font-size='30' font-weight='700' fill='%232c3335'%3ESTEP2 REVIEW PDF PREVIEW%3C/text%3E%3Ctext x='420' y='236' text-anchor='middle' font-family='Arial' font-size='22' fill='%2357666b'%3E000 high accuracy OCR test file%3C/text%3E%3Cline x1='146' y1='328' x2='694' y2='328' stroke='%23919892' stroke-width='2'/%3E%3Cline x1='146' y1='400' x2='694' y2='400' stroke='%23919892' stroke-width='2'/%3E%3Cline x1='146' y1='472' x2='694' y2='472' stroke='%23919892' stroke-width='2'/%3E%3Cline x1='146' y1='544' x2='694' y2='544' stroke='%23919892' stroke-width='2'/%3E%3Cline x1='146' y1='616' x2='694' y2='616' stroke='%23919892' stroke-width='2'/%3E%3Crect x='146' y='720' width='548' height='210' fill='none' stroke='%23919892' stroke-width='2'/%3E%3Ctext x='170' y='770' font-family='Arial' font-size='24' fill='%23333'%3EReview mode placeholder%3C/text%3E%3Ctext x='170' y='820' font-family='Arial' font-size='20' fill='%2357666b'%3EUse this screen for layout feedback.%3C/text%3E%3C/svg%3E";
const devPreviewOutputDir = "C:\\Users\\admin\\Desktop";
const devPreviewMetadata: SegmentMetadata = {
  [`${step2ReviewPdfPath}#1-3`]: { box_no: "1", binder_no: "1", seq: "1" },
  [`${step2ReviewPdfPath}#4-7`]: { box_no: "1", binder_no: "1", seq: "2" },
  [`${step2ReviewPdfPath}#8-11`]: { box_no: "1", binder_no: "1", seq: "3" }
};
const devPreviewChecks: SidecarOutputCheck[] = [
  {
    existing_path: "",
    filename: "01_01_001.pdf",
    has_existing_output: false,
    messages: [],
    metadata: devPreviewMetadata[`${step2ReviewPdfPath}#1-3`],
    ok: true,
    output_path: `${devPreviewOutputDir}\\01_01_001.pdf`,
    pages: "1-3",
    pdf_path: step2ReviewPdfPath,
    requested_filename: "01_01_001.pdf",
    requested_path: `${devPreviewOutputDir}\\01_01_001.pdf`
  },
  {
    existing_path: `${devPreviewOutputDir}\\01_01_002.pdf`,
    filename: "01_01_002.pdf",
    has_existing_output: true,
    messages: ["output_exists"],
    metadata: devPreviewMetadata[`${step2ReviewPdfPath}#4-7`],
    ok: false,
    output_path: "",
    pages: "4-7",
    pdf_path: step2ReviewPdfPath,
    requested_filename: "01_01_002.pdf",
    requested_path: `${devPreviewOutputDir}\\01_01_002.pdf`
  },
  {
    existing_path: "",
    filename: "01_01_003.pdf",
    has_existing_output: false,
    messages: [],
    metadata: devPreviewMetadata[`${step2ReviewPdfPath}#8-11`],
    ok: true,
    output_path: `${devPreviewOutputDir}\\01_01_003.pdf`,
    pages: "8-11",
    pdf_path: step2ReviewPdfPath,
    requested_filename: "01_01_003.pdf",
    requested_path: `${devPreviewOutputDir}\\01_01_003.pdf`
  }
];
const devPreviewSearchResults: MergedSearchResult[] = [
  {
    matchedTerms: ["契約書", "請求書"],
    pageNo: 4,
    pdfPath: step2ReviewPdfPath,
    snippets: ["契約書 OCR test file searchable preview text", "請求書 sample line"],
    totalCount: 3
  },
  {
    matchedTerms: ["契約書"],
    pageNo: 8,
    pdfPath: step2ReviewPdfPath,
    snippets: ["契約書 page for output review"],
    totalCount: 1
  }
];
const devPreviewSearchHighlights: TermSearchHighlightRect[] = [
  { page_height: 1188, page_width: 840, term: "契約書", x0: 300, x1: 396, y0: 214, y1: 246 },
  { page_height: 1188, page_width: 840, term: "請求書", x0: 468, x1: 520, y0: 214, y1: 246 }
];
const devPreviewIndexCandidates: IndexCandidate[] = [
  {
    page_no: 1,
    pdf_path: step2ReviewPdfPath,
    reason: "表紙",
    score: 0.82,
    snippet: "表紙に近い文言を検出しました。"
  },
  {
    page_no: 4,
    pdf_path: step2ReviewPdfPath,
    reason: "No.",
    score: 0.74,
    snippet: "No. / 書類名に近い候補語を検出しました。"
  },
  {
    page_no: 8,
    pdf_path: step2ReviewPdfPath,
    reason: "区切り",
    score: 0.69,
    snippet: "区切り候補として確認が必要なページです。"
  }
];
const devPreviewBlankCandidates: SidecarBlankCandidate[] = [{ page_no: 11, score: 0.9921 }];

function basename(path: string): string {
  return path.split(/[\\/]/).filter(Boolean).pop() ?? path;
}

function sidecarError(response: SidecarResponse): string {
  return "error" in response ? response.error : "Sidecar response is not usable for this operation.";
}

function isEditableKeyboardTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }
  return target.matches("input, textarea, select") || target.isContentEditable;
}

function normalizeSearchTerm(term: string): string {
  return term.trim();
}

function uniqueSearchTerms(terms: string[]): string[] {
  const seen = new Set<string>();
  const normalized: string[] = [];
  for (const term of terms.map(normalizeSearchTerm)) {
    if (!term || seen.has(term)) {
      continue;
    }
    seen.add(term);
    normalized.push(term);
  }
  return normalized;
}

function selectedSearchTermsFromPreset(preset: SearchTermPreset): SelectedSearchTerm[] {
  const customSet = new Set(preset.customTerms);
  return uniqueSearchTerms(preset.selectedTerms).map((term) => ({
    source: customSet.has(term) ? "custom" : "built_in",
    term
  }));
}

function defaultSearchTermPreset(): SearchTermPreset {
  return {
    customTerms: [],
    selectedTerms: defaultSelectedSearchTerms
  };
}

function loadSearchTermPreset(): SearchTermPreset {
  if (typeof window === "undefined") {
    return defaultSearchTermPreset();
  }
  try {
    const raw = window.localStorage.getItem(SEARCH_TERM_PRESET_STORAGE_KEY);
    if (!raw) {
      return defaultSearchTermPreset();
    }
    const parsed = JSON.parse(raw) as Partial<SearchTermPreset>;
    return {
      customTerms: uniqueSearchTerms(Array.isArray(parsed.customTerms) ? parsed.customTerms : []),
      selectedTerms: uniqueSearchTerms(
        Array.isArray(parsed.selectedTerms) && parsed.selectedTerms.length ? parsed.selectedTerms : defaultSelectedSearchTerms
      )
    };
  } catch {
    return defaultSearchTermPreset();
  }
}

function saveSearchTermPreset(preset: SearchTermPreset): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(
    SEARCH_TERM_PRESET_STORAGE_KEY,
    JSON.stringify({
      customTerms: uniqueSearchTerms(preset.customTerms),
      selectedTerms: uniqueSearchTerms(preset.selectedTerms)
    })
  );
}

function isDevBrowserPreview(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  const params = new URLSearchParams(window.location.search);
  const env = typeof process !== "undefined" ? process.env.NODE_ENV : "development";
  const hasDevQuery = params.has("dev") || params.get("review") === "step2";
  const isTauriRuntime = "__TAURI_INTERNALS__" in window || "__TAURI__" in window;
  const isLocalBrowser = ["localhost", "127.0.0.1"].includes(window.location.hostname);
  return !isTauriRuntime && isLocalBrowser && (env === "development" || hasDevQuery);
}

function devStepFromUrl(): DevPreviewStep {
  if (typeof window === "undefined") {
    return "split";
  }
  const params = new URLSearchParams(window.location.search);
  if (params.get("review") === "step2") {
    return "split";
  }
  const devStep = params.get("dev");
  return steps.some((step) => step.id === devStep) ? (devStep as DevPreviewStep) : "split";
}

function shouldUseDevPreviewMode(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  return isDevBrowserPreview() || new URLSearchParams(window.location.search).get("review") === "step2";
}

function IconLabel({ children, icon: Icon }: { children: ReactNode; icon: LucideIcon }) {
  return (
    <span className="icon-label">
      <Icon aria-hidden="true" size={16} strokeWidth={2.1} />
      <span>{children}</span>
    </span>
  );
}

function EmptyState({
  action,
  children,
  icon: Icon,
  title
}: {
  action?: ReactNode;
  children: ReactNode;
  icon: LucideIcon;
  title: string;
}) {
  return (
    <div className="empty-state">
      <Icon aria-hidden="true" size={28} strokeWidth={1.9} />
      <div>
        <strong>{title}</strong>
        <p>{children}</p>
      </div>
      {action}
    </div>
  );
}

function PaneHeader({
  action,
  description,
  title
}: {
  action?: ReactNode;
  description?: string;
  title: string;
}) {
  return (
    <div className="pane-header">
      <div>
        <h3>{title}</h3>
        {description ? <p>{description}</p> : null}
      </div>
      {action}
    </div>
  );
}

function StatusCheck({ detail, label, ok }: { detail?: string; label: string; ok: boolean }) {
  return (
    <div className={ok ? "status-check ok" : "status-check warning"}>
      {ok ? (
        <CheckCircle2 aria-hidden="true" size={17} strokeWidth={2.2} />
      ) : (
        <AlertTriangle aria-hidden="true" size={17} strokeWidth={2.2} />
      )}
      <span>
        <strong>{label}</strong>
        {detail ? <small>{detail}</small> : null}
      </span>
    </div>
  );
}

function StatLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="stat-line">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function segmentPreviewPages(segment: SegmentView): number[] {
  const pageCount = segment.endPage - segment.startPage + 1;
  const visibleCount = Math.min(pageCount, 4);
  return Array.from({ length: visibleCount }, (_, index) => segment.startPage + index);
}

export default function Page() {
  const [activeStep, setActiveStep] = useState<StepId>("import");
  const [pdfFiles, setPdfFiles] = useState<PdfFile[]>([]);
  const [currentPdf, setCurrentPdf] = useState("");
  const [currentPage, setCurrentPage] = useState(1);
  const [previewDataUrl, setPreviewDataUrl] = useState("");
  const [outputDir, setOutputDir] = useState("");
  const [commonMetadata, setCommonMetadata] = useState<Record<string, string>>(defaultCommonMetadata);
  const [splitPointsByPdf, setSplitPointsByPdf] = useState<Record<string, number[]>>({});
  const [segmentMetadata, setSegmentMetadata] = useState<SegmentMetadata>({});
  const [affixDefs, setAffixDefs] = useState<AffixDef[]>([]);
  const [seqStart, setSeqStart] = useState(1);
  const [seqDigits, setSeqDigits] = useState(DEFAULT_SEQ_DIGITS);
  // STEP3 右カラム「追加項目」アコーディオンの開閉。null=既定(項目があれば開く)に従い、
  // ユーザーが操作したら明示値を保持する（セッション内・セグメント切替では保持）。
  const [affixExpandedOverride, setAffixExpandedOverride] = useState<boolean | null>(null);
  const [transcribeTargetKey, setTranscribeTargetKey] = useState("");
  const [selectedSegmentKey, setSelectedSegmentKey] = useState("");
  const [preflightChecks, setPreflightChecks] = useState<SidecarOutputCheck[]>([]);
  const [exportResult, setExportResult] = useState<SidecarExportResponse | null>(null);
  const [isPreflighting, setIsPreflighting] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const [status, setStatus] = useState("PDFを選択してください。");
  const [currentVersion, setCurrentVersion] = useState("0.1.0");
  const [updateState, setUpdateState] = useState<UpdateState>("idle");
  const [updateMessage, setUpdateMessage] = useState("更新未確認");
  const [updateProgress, setUpdateProgress] = useState("");
  const [availableUpdate, setAvailableUpdate] = useState<AppUpdate | null>(null);
  const [devPreviewEnabled, setDevPreviewEnabled] = useState(false);
  const [previewFitMode, setPreviewFitMode] = useState<PreviewFitMode>("page");
  const [previewZoom, setPreviewZoom] = useState(1.2);
  const [selectedSplitPoint, setSelectedSplitPoint] = useState<number | null>(null);
  const [splitHistory, setSplitHistory] = useState<{ past: SplitHistoryEntry[]; future: SplitHistoryEntry[] }>({
    future: [],
    past: []
  });
  const [pageText, setPageText] = useState("");
  const [pageTextStatus, setPageTextStatus] = useState("OCRテキスト未取得");
  const [customSearchTerms, setCustomSearchTerms] = useState<string[]>([]);
  const [selectedSearchTerms, setSelectedSearchTerms] = useState<SelectedSearchTerm[]>(
    selectedSearchTermsFromPreset(defaultSearchTermPreset())
  );
  const [searchTermModalOpen, setSearchTermModalOpen] = useState(false);
  const [draftSelectedSearchTerms, setDraftSelectedSearchTerms] = useState<string[]>(defaultSelectedSearchTerms);
  const [draftCustomSearchTerms, setDraftCustomSearchTerms] = useState<string[]>([]);
  const [customSearchTermInput, setCustomSearchTermInput] = useState("");
  const [searchResults, setSearchResults] = useState<MergedSearchResult[]>([]);
  const [selectedSearchHit, setSelectedSearchHit] = useState<SelectedSearchHit | null>(null);
  const [searchHighlights, setSearchHighlights] = useState<TermSearchHighlightRect[]>([]);
  const [indexCandidates, setIndexCandidates] = useState<IndexCandidate[]>([]);
  const [blankCandidates, setBlankCandidates] = useState<SidecarBlankCandidate[]>([]);
  const [pageThumbnails, setPageThumbnails] = useState<Record<string, string>>({});
  const previewRequestGateRef = useRef(createPreviewRequestGate());
  const workspaceRequestGateRef = useRef(createPreviewRequestGate());
  const pageTextRequestGateRef = useRef(createPreviewRequestGate());
  const pdfAuxiliaryRequestGateRef = useRef(createPreviewRequestGate());
  const zoomReloadTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // 出力前チェック/出力実行の二重起動を同期的に防ぐ（連打対策。state は表示用 disable）。
  const preflightInFlightRef = useRef(false);
  const exportInFlightRef = useRef(false);
  // 連番を手動で上書きしたセグメントキー（再採番で保護。state に保存・復元される）。
  const manualSeqKeysRef = useRef<Set<string>>(new Set());
  // 取得済みサムネイルのキー（`${pdfPath}#${pageNo}`）。PDF再選択時の再取得を防ぐ。
  const loadedThumbnailKeysRef = useRef<Set<string>>(new Set());
  // キーボードハンドラは ref 経由で最新を呼び、リスナー登録はマウント時1回に固定する
  // （毎レンダーの addEventListener/removeEventListener 再登録を避ける）。
  const step2KeyHandlerRef = useRef<(event: KeyboardEvent) => void>(() => {});
  const step3KeyHandlerRef = useRef<(event: KeyboardEvent) => void>(() => {});

  const currentFile = pdfFiles.find((file) => file.path === currentPdf);
  const allSegments = useMemo(
    () => buildSegments(pdfFiles, splitPointsByPdf, segmentMetadata, commonMetadata),
    [pdfFiles, splitPointsByPdf, segmentMetadata, commonMetadata]
  );
  // セグメント構成（キーと順序）の変化を検知するための安定したシグネチャ。
  const segmentKeysSignature = useMemo(() => allSegments.map((segment) => segment.key).join("|"), [allSegments]);
  const currentVisibleSegment = useMemo(
    () =>
      allSegments.find(
        (segment) =>
          segment.pdfPath === currentPdf && segment.startPage <= currentPage && segment.endPage >= currentPage
      ),
    [allSegments, currentPage, currentPdf]
  );
  const currentPdfSplitPointCount = currentFile ? splitPointsFor(currentFile.pageCount, splitPointsByPdf[currentFile.path]).length : 0;
  const selectedSegment = allSegments.find((segment) => segment.key === selectedSegmentKey) ?? allSegments[0];
  const currentPdfSegments = allSegments.filter((segment) => segment.pdfPath === currentPdf);
  const currentSplitPoints = currentFile ? splitPointsFor(currentFile.pageCount, splitPointsByPdf[currentFile.path]) : [];
  const selectedSearchTermValues = useMemo(
    () => selectedSearchTerms.map((item) => item.term),
    [selectedSearchTerms]
  );
  const currentPageStates = useMemo<PageState[]>(() => {
    if (!currentFile) {
      return [];
    }
    return Array.from({ length: currentFile.pageCount }, (_value, index) => {
      const pageNo = index + 1;
      const segment =
        currentPdfSegments.find((item) => item.startPage <= pageNo && item.endPage >= pageNo) ?? null;
      const blankCandidate = blankCandidates.find((candidate) => candidate.page_no === pageNo);
      return {
        blankScore: blankCandidate?.score,
        hasSplitBefore: currentSplitPoints.includes(pageNo),
        isCurrent: pageNo === currentPage,
        pageNo,
        segment,
        thumbnail: pageThumbnails[`${currentFile.path}#${pageNo}`]
      };
    });
  }, [blankCandidates, currentFile, currentPage, currentPdfSegments, currentSplitPoints, pageThumbnails]);
  const totalPages = useMemo(() => pdfFiles.reduce((total, file) => total + file.pageCount, 0), [pdfFiles]);
  const incompleteSegments = useMemo(
    () => allSegments.filter((segment) => missingMetadata(segment.metadata).length > 0).length,
    [allSegments]
  );
  const readySegments = Math.max(0, allSegments.length - incompleteSegments);
  const outputIssues = outputIssueCount(preflightChecks);
  const existingOutputs = preflightChecks.filter((check) => check.has_existing_output).length;
  const canContinueFromImport = pdfFiles.length > 0 && Boolean(outputDir);
  const canRunPreflight = allSegments.length > 0 && Boolean(outputDir);
  const canExport = preflightChecks.length > 0 && outputIssues === 0 && existingOutputs === 0;

  function clearOutputState(): void {
    setPreflightChecks([]);
    setExportResult(null);
  }

  function clearLegacyStep2AuxiliaryState(): void {
    setPageText("");
    setPageTextStatus("OCRテキスト未取得");
    setSearchResults([]);
    setSelectedSearchHit(null);
    setSearchHighlights([]);
    setIndexCandidates([]);
    setBlankCandidates([]);
    setPageThumbnails({});
    loadedThumbnailKeysRef.current.clear();
    setSelectedSplitPoint(null);
    setSplitHistory({ future: [], past: [] });
  }

  function applyDevPreviewState(step: DevPreviewStep): void {
    const selectedKey = step === "output" ? `${step2ReviewPdfPath}#8-11` : `${step2ReviewPdfPath}#4-7`;
    const currentPageForStep = step === "output" ? 8 : 4;
    const searchTermPreset = loadSearchTermPreset();
    const devSelectedSearchTerms = selectedSearchTermsFromPreset(searchTermPreset);
    const devSelectedTermValues = devSelectedSearchTerms.map((item) => item.term);
    const devSearchResultsForTerms = devPreviewSearchResults.filter((result) =>
      result.matchedTerms.some((term) => devSelectedTermValues.includes(term))
    );
    const devSearchHighlightsForTerms = devPreviewSearchHighlights.filter((rect) =>
      devSelectedTermValues.includes(rect.term)
    );

    invalidateWorkspaceAndPreviewRequests();
    previewCache.clear();
    setActiveStep(step);
    setPdfFiles([{ path: step2ReviewPdfPath, pageCount: 11 }]);
    setCurrentPdf(step2ReviewPdfPath);
    setCurrentPage(currentPageForStep);
    setPreviewDataUrl(step2ReviewPreviewDataUrl);
    setOutputDir(devPreviewOutputDir);
    setCommonMetadata(defaultCommonMetadata);
    setSplitPointsByPdf({ [step2ReviewPdfPath]: [4, 8] });
    setSegmentMetadata(devPreviewMetadata);
    setSelectedSegmentKey(selectedKey);
    setPreflightChecks(step === "output" ? devPreviewChecks : []);
    setExportResult(
      step === "output"
        ? {
            command: "export",
            items: devPreviewChecks.map((check, index) => ({
              ...check,
              sha256: `dev-preview-sha256-${index + 1}`,
              status: "created"
            })),
            messages: ["デベロッパーモードの出力結果サンプルです。"],
            ok: true,
            output_dir: devPreviewOutputDir,
            summary: { created: devPreviewChecks.length, failed: 0 }
          }
        : null
    );
    setPreviewFitMode("page");
    setPreviewZoom(1.2);
    setSelectedSplitPoint(4);
    setSplitHistory({ future: [], past: [] });
    setPageText("000高精度ocrのテスト用ファイル_searchable.pdf の4ページ目に相当する契約書と請求書の検索可能テキストプレビューです。OCRテキスト欄、用語ハイライト、白紙候補の配置確認に使います。");
    setPageTextStatus("検索可能PDFのテキストレイヤーを表示中");
    setCustomSearchTerms(searchTermPreset.customTerms);
    setSelectedSearchTerms(devSelectedSearchTerms);
    setDraftSelectedSearchTerms(searchTermPreset.selectedTerms);
    setDraftCustomSearchTerms(searchTermPreset.customTerms);
    setCustomSearchTermInput("");
    setSearchResults(devSearchResultsForTerms);
    setSelectedSearchHit(
      devSearchResultsForTerms.length
        ? { index: 0, pageNo: devSearchResultsForTerms[0].pageNo, pdfPath: step2ReviewPdfPath }
        : null
    );
    setSearchHighlights(devSearchHighlightsForTerms);
    setIndexCandidates(devPreviewIndexCandidates);
    setBlankCandidates(devPreviewBlankCandidates);
    setPageThumbnails({});
    loadedThumbnailKeysRef.current.clear();
    setStatus("DEVプレビュー: サンプルPDFを読み込んだ本番想定画面です。");
  }

  function switchDevPreviewStep(step: DevPreviewStep): void {
    applyDevPreviewState(step);
    const url = new URL(window.location.href);
    url.searchParams.delete("review");
    url.searchParams.set("dev", step);
    window.history.replaceState(null, "", url);
  }

  function applySplitPointsForPdf(pdfPath: string, pageCount: number, nextPoints: number[]): void {
    const previousPoints = splitPointsFor(pageCount, splitPointsByPdf[pdfPath]);
    const normalizedPoints = splitPointsFor(pageCount, nextPoints);
    setSegmentMetadata((metadata) =>
      reconcileSegmentMetadataForPdf({
        pageCount,
        pdfPath,
        previousSplitPoints: previousPoints,
        nextSplitPoints: normalizedPoints,
        segmentMetadata: metadata
      })
    );
    setSplitPointsByPdf((current) => ({
      ...current,
      [pdfPath]: normalizedPoints
    }));
  }

  function updateCurrentPdfSplitPoints(nextPointsFor: (currentPoints: number[]) => number[], recordHistory = true): void {
    if (!currentFile) {
      return;
    }

    const pdfPath = currentFile.path;
    const pageCount = currentFile.pageCount;
    const previousPoints = splitPointsFor(pageCount, splitPointsByPdf[pdfPath]);
    const nextPoints = splitPointsFor(pageCount, nextPointsFor(previousPoints));
    if (previousPoints.join(",") === nextPoints.join(",")) {
      return;
    }
    if (recordHistory) {
      setSplitHistory((current) => ({
        future: [],
        past: [...current.past.slice(-24), { pdfPath, points: previousPoints }]
      }));
    }

    setSegmentMetadata((metadata) =>
      reconcileSegmentMetadataForPdf({
        pageCount,
        pdfPath,
        previousSplitPoints: previousPoints,
        nextSplitPoints: nextPoints,
        segmentMetadata: metadata
      })
    );
    setSplitPointsByPdf((current) => ({
      ...current,
      [pdfPath]: nextPoints
    }));
  }

  async function selectPageForPreview(pdfPath: string, pageNo: number): Promise<void> {
    const file = pdfFiles.find((item) => item.path === pdfPath);
    if (!file) {
      return;
    }
    const nextPage = Math.max(1, Math.min(file.pageCount, pageNo));
    invalidateWorkspaceRequests();
    setCurrentPdf(pdfPath);
    if (devPreviewEnabled) {
      setCurrentPage(nextPage);
      setPreviewDataUrl(step2ReviewPreviewDataUrl);
      setPageText(
        `${basename(pdfPath)} の${nextPage}ページ目に相当する検索可能テキストのプレビューです。OCR、インデックス、書類名、会社名などの検索支援表示を確認できます。`
      );
      setPageTextStatus("検索可能PDFのテキストレイヤーを表示中");
    }
    const nextSegment = allSegments.find(
      (segment) => segment.pdfPath === pdfPath && segment.startPage <= nextPage && segment.endPage >= nextPage
    );
    setSelectedSegmentKey(nextSegment?.key ?? "");
    if (devPreviewEnabled) {
      return;
    }
    try {
      await loadPreview(pdfPath, nextPage);
    } catch (error) {
      setStatus(`プレビューエラー: ${String(error)}`);
    }
  }

  async function movePdf(offset: number): Promise<void> {
    if (!currentPdf || !pdfFiles.length) {
      return;
    }
    const currentIndex = Math.max(0, pdfFiles.findIndex((file) => file.path === currentPdf));
    const nextFile = pdfFiles[Math.max(0, Math.min(pdfFiles.length - 1, currentIndex + offset))];
    if (!nextFile || nextFile.path === currentPdf) {
      return;
    }
    await selectPageForPreview(nextFile.path, 1);
  }

  useEffect(() => {
    let disposed = false;

    void readCurrentVersion()
      .then((version) => {
        if (!disposed) {
          setCurrentVersion(version);
        }
      })
      .catch(() => {
        if (!disposed) {
          setCurrentVersion("0.1.0");
        }
      });

    void checkForUpdates(false, () => disposed);

    return () => {
      disposed = true;
    };
  }, []);

  useEffect(() => {
    let disposed = false;

    async function initializeDefaultOutputDir(): Promise<void> {
      try {
        const defaultOutputDir = await desktopDir();
        if (!disposed) {
          setOutputDir((current) => current || defaultOutputDir);
        }
      } catch {
        // Browser preview cannot resolve a desktop directory. Keep the field empty there.
      }
    }

    void initializeDefaultOutputDir();

    return () => {
      disposed = true;
    };
  }, []);

  useEffect(() => {
    const preset = loadSearchTermPreset();
    setCustomSearchTerms(preset.customTerms);
    setSelectedSearchTerms(selectedSearchTermsFromPreset(preset));
    setDraftSelectedSearchTerms(preset.selectedTerms);
    setDraftCustomSearchTerms(preset.customTerms);
  }, []);

  useEffect(() => {
    if (!shouldUseDevPreviewMode()) {
      return;
    }

    setDevPreviewEnabled(true);
    applyDevPreviewState(devStepFromUrl());
  }, []);

  useEffect(() => {
    if (!currentFile || devPreviewEnabled) {
      return;
    }
    const requestId = pageTextRequestGateRef.current.next();

    async function loadCurrentPageText(): Promise<void> {
      try {
        const response = await invokeSidecar({ command: "page_text", pdf_path: currentFile!.path, page_no: currentPage });
        if (!pageTextRequestGateRef.current.isCurrent(requestId)) {
          return;
        }
        if (!response.ok || response.command !== "page_text") {
          setPageText("");
          setPageTextStatus(response.ok ? "OCRテキストを取得できませんでした。" : sidecarError(response));
          return;
        }
        const pageResponse = response as SidecarPageTextResponse;
        setPageText(pageResponse.text);
        setPageTextStatus(pageResponse.has_text ? "検索可能PDFのテキストレイヤーを表示中" : "テキストなし");
      } catch (error) {
        if (pageTextRequestGateRef.current.isCurrent(requestId)) {
          setPageText("");
          setPageTextStatus(`OCRテキスト取得エラー: ${String(error)}`);
        }
      }
    }

    void loadCurrentPageText();
  }, [currentFile, currentPage, devPreviewEnabled]);

  useEffect(() => {
    if (!currentFile || devPreviewEnabled) {
      return;
    }
    const requestId = pdfAuxiliaryRequestGateRef.current.next();

    const pdfPath = currentFile.path;
    const pageCount = currentFile.pageCount;
    // サイドカーは1リクエスト1プロセス起動のため、並列度は控えめ(4)に抑える（根治は #81 常駐化）。
    const THUMBNAIL_CONCURRENCY = 4;
    const MAX_THUMBNAILS = 60;

    async function loadCurrentPdfAuxiliaryData(): Promise<void> {
      // blank_candidates はサムネイルと独立。並行で投げ、サムネイル取得をブロックしない。
      const blankPromise = invokeSidecar({ command: "blank_candidates", pdf_path: pdfPath })
        .then((blankResponse) => {
          if (!pdfAuxiliaryRequestGateRef.current.isCurrent(requestId)) {
            return;
          }
          if (blankResponse.ok && blankResponse.command === "blank_candidates") {
            setBlankCandidates(blankResponse.candidates);
          }
        })
        .catch(() => {
          if (pdfAuxiliaryRequestGateRef.current.isCurrent(requestId)) {
            setBlankCandidates([]);
          }
        });

      // 未取得サムネイルだけを、並列度を絞ってチャンク取得し、チャンクごとに1回だけまとめてsetStateする。
      const pendingPages = Array.from({ length: Math.min(pageCount, MAX_THUMBNAILS) }, (_value, index) => index + 1).filter(
        (pageNo) => !loadedThumbnailKeysRef.current.has(`${pdfPath}#${pageNo}`)
      );
      for (let offset = 0; offset < pendingPages.length; offset += THUMBNAIL_CONCURRENCY) {
        if (!pdfAuxiliaryRequestGateRef.current.isCurrent(requestId)) {
          return;
        }
        const chunk = pendingPages.slice(offset, offset + THUMBNAIL_CONCURRENCY);
        const responses = await Promise.all(
          chunk.map((pageNo) =>
            invokeSidecar({ command: "page_thumbnail", pdf_path: pdfPath, page_no: pageNo })
              .then((response) => (response.ok && response.command === "page_thumbnail" ? response : null))
              .catch(() => null)
          )
        );
        if (!pdfAuxiliaryRequestGateRef.current.isCurrent(requestId)) {
          return;
        }
        const batch: Record<string, string> = {};
        for (const response of responses) {
          if (response) {
            const key = `${response.pdf_path}#${response.page_no}`;
            batch[key] = response.image_data_url;
            loadedThumbnailKeysRef.current.add(key);
          }
        }
        if (Object.keys(batch).length) {
          setPageThumbnails((current) => ({ ...current, ...batch }));
        }
      }

      await blankPromise;
    }

    void loadCurrentPdfAuxiliaryData();
  }, [currentFile, devPreviewEnabled]);

  async function checkForUpdates(manual: boolean, isDisposed: () => boolean = () => false): Promise<void> {
    setUpdateState("checking");
    setUpdateMessage("更新を確認しています。");
    setUpdateProgress("");
    if (manual) {
      setStatus("更新を確認しています。");
    }
    try {
      const update = await checkForAppUpdate();
      if (isDisposed()) {
        return;
      }
      setAvailableUpdate(update);
      if (update) {
        setUpdateState("available");
        setUpdateMessage(`新しいバージョン ${update.version} があります。`);
        setStatus(`新しいバージョン ${update.version} があります。`);
        return;
      }
      setUpdateState("current");
      setUpdateMessage("最新版です。");
      if (manual) {
        setStatus("最新版です。");
      }
    } catch (error) {
      if (isDisposed()) {
        return;
      }
      const message = updateErrorMessage(error);
      setAvailableUpdate(null);
      setUpdateState("error");
      setUpdateMessage(message);
      if (manual) {
        setStatus(`更新確認エラー: ${message}`);
      }
    }
  }

  async function installAvailableUpdate(): Promise<void> {
    if (!availableUpdate) {
      return;
    }
    setUpdateState("installing");
    setUpdateMessage("更新をダウンロードしています。");
    setUpdateProgress("");
    setStatus("更新をダウンロードしています。");
    try {
      await installAppUpdate(availableUpdate, (progress) => {
        if (progress.finished) {
          setUpdateProgress("ダウンロード完了");
          return;
        }
        if (progress.contentLength && progress.contentLength > 0) {
          const percent = Math.min(100, Math.round((progress.downloadedBytes / progress.contentLength) * 100));
          setUpdateProgress(`${percent}%`);
          return;
        }
        setUpdateProgress(`${Math.round(progress.downloadedBytes / 1024)} KB`);
      });
      setUpdateState("installed");
      setUpdateMessage("更新をインストールしました。再起動します。");
      setStatus("更新をインストールしました。");
    } catch (error) {
      const message = updateErrorMessage(error);
      setUpdateState("error");
      setUpdateMessage(`更新インストールに失敗しました: ${message}`);
      setStatus(`更新インストールエラー: ${message}`);
    }
  }

  function stepState(stepId: StepId): StepState {
    if (activeStep === stepId) {
      return "active";
    }
    if (stepId === "import") {
      return canContinueFromImport ? "done" : pdfFiles.length || outputDir ? "attention" : "idle";
    }
    if (stepId === "split") {
      return allSegments.length ? "done" : "idle";
    }
    if (stepId === "input") {
      if (!allSegments.length) {
        return "idle";
      }
      return incompleteSegments ? "attention" : "done";
    }
    if (exportResult?.summary.created) {
      return "done";
    }
    if (outputIssues) {
      return "attention";
    }
    return "idle";
  }

  function stepStateLabel(state: StepState): string {
    if (state === "active") {
      return "作業中";
    }
    if (state === "done") {
      return "完了";
    }
    if (state === "attention") {
      return "要確認";
    }
    return "未着手";
  }

  async function loadPdfInfo(path: string): Promise<PdfFile> {
    const response = await invokeSidecar({ command: "pdf_info", pdf_path: path });
    if (!response.ok || response.command !== "pdf_info") {
      throw new Error(response.ok ? "PDF情報を取得できませんでした。" : sidecarError(response));
    }
    const info = response as SidecarPdfInfoResponse;
    return { path: info.pdf_path, pageCount: info.page_count };
  }

  function invalidatePreviewRequests(): void {
    previewRequestGateRef.current.invalidate();
  }

  function invalidateWorkspaceRequests(): void {
    workspaceRequestGateRef.current.invalidate();
  }

  // 指定PDFのサムネイルキャッシュ鍵を破棄し、次回選択時に再取得させる。
  function purgeThumbnailKeysForPath(path: string): void {
    const prefix = `${path}#`;
    for (const key of [...loadedThumbnailKeysRef.current]) {
      if (key.startsWith(prefix)) {
        loadedThumbnailKeysRef.current.delete(key);
      }
    }
  }

  function invalidateWorkspaceAndPreviewRequests(): void {
    invalidateWorkspaceRequests();
    invalidatePreviewRequests();
  }

  async function loadPreview(pdfPath: string, pageNo: number, zoomOverride = previewZoom): Promise<void> {
    await loadPagePreview({
      applyPreview(preview) {
        setPreviewDataUrl(preview.imageDataUrl);
        setCurrentPage(preview.pageNo);
      },
      cache: previewCache,
      gate: previewRequestGateRef.current,
      invalidPreviewMessage: "プレビューを取得できませんでした。",
      pageNo,
      pdfPath,
      requestPreview: (request) => invokeSidecar(request),
      responseErrorMessage: (response) => sidecarError(response as SidecarResponse),
      zoom: zoomOverride
    });
  }

  async function choosePdfs(): Promise<void> {
    let requestId = 0;
    try {
      const selected = await open({
        multiple: true,
        filters: [{ name: "PDF", extensions: ["pdf"] }]
      });
      const paths = Array.isArray(selected) ? selected : selected ? [selected] : [];
      if (!paths.length) {
        return;
      }
      requestId = workspaceRequestGateRef.current.next();
      invalidatePreviewRequests();
      for (const path of paths) {
        previewCache.clearPdf(path);
        purgeThumbnailKeysForPath(path);
      }
      const loaded = await Promise.all(paths.map((path) => loadPdfInfo(path)));
      if (!workspaceRequestGateRef.current.isCurrent(requestId)) {
        return;
      }
      setPdfFiles((existing) => {
        const byPath = new Map(existing.map((file) => [file.path, file]));
        for (const file of loaded) {
          byPath.set(file.path, file);
        }
        return [...byPath.values()];
      });
      setCurrentPdf(loaded[0].path);
      setCurrentPage(1);
      clearOutputState();
      await loadPreview(loaded[0].path, 1);
      if (!workspaceRequestGateRef.current.isCurrent(requestId)) {
        return;
      }
      setStatus(`${loaded.length}件のPDFを読み込みました。`);
    } catch (error) {
      if (requestId && !workspaceRequestGateRef.current.isCurrent(requestId)) {
        return;
      }
      setStatus(`PDF取込エラー: ${String(error)}`);
    }
  }

  async function chooseOutputDir(): Promise<void> {
    const selected = await open({ directory: true, multiple: false });
    if (typeof selected === "string") {
      invalidateWorkspaceRequests();
      setOutputDir(selected);
      clearOutputState();
      setStatus("出力フォルダを設定しました。");
    }
  }

  async function selectPdf(path: string): Promise<void> {
    invalidateWorkspaceRequests();
    setCurrentPdf(path);
    setCurrentPage(1);
    try {
      await loadPreview(path, 1);
    } catch (error) {
      setStatus(`プレビューエラー: ${String(error)}`);
    }
  }

  async function selectSegmentForPreview(segment: SegmentView): Promise<void> {
    invalidateWorkspaceRequests();
    setSelectedSegmentKey(segment.key);
    setCurrentPdf(segment.pdfPath);
    setCurrentPage(segment.startPage);
    try {
      await loadPreview(segment.pdfPath, segment.startPage);
    } catch (error) {
      setStatus(`プレビューエラー: ${String(error)}`);
    }
  }

  async function removePdf(path: string): Promise<void> {
    const remaining = pdfFiles.filter((file) => file.path !== path);
    invalidateWorkspaceAndPreviewRequests();
    previewCache.clearPdf(path);
    purgeThumbnailKeysForPath(path);
    setPdfFiles(remaining);
    setSplitPointsByPdf((current) => {
      const next = { ...current };
      delete next[path];
      return next;
    });
    setSegmentMetadata((current) => {
      const next: Record<string, Record<string, string>> = {};
      for (const [key, value] of Object.entries(current)) {
        if (!key.startsWith(`${path}#`)) {
          next[key] = value;
        }
      }
      return next;
    });
    if (selectedSegmentKey.startsWith(`${path}#`)) {
      setSelectedSegmentKey("");
    }
    clearOutputState();
    if (currentPdf === path) {
      const nextPdf = remaining[0];
      setCurrentPdf(nextPdf?.path ?? "");
      setCurrentPage(1);
      setPreviewDataUrl("");
      if (nextPdf) {
        try {
          await loadPreview(nextPdf.path, 1);
        } catch (error) {
          setStatus(`プレビューエラー: ${String(error)}`);
          return;
        }
      }
    }
    setStatus(`${basename(path)} を一覧から外しました。`);
  }

  function clearPdfSelection(): void {
    invalidateWorkspaceAndPreviewRequests();
    previewCache.clear();
    setPdfFiles([]);
    setCurrentPdf("");
    setCurrentPage(1);
    setPreviewDataUrl("");
    setSplitPointsByPdf({});
    setSegmentMetadata({});
    setSelectedSegmentKey("");
    clearLegacyStep2AuxiliaryState();
    clearOutputState();
    setStatus("PDF一覧をクリアしました。");
  }

  async function resetOutputDir(): Promise<void> {
    invalidateWorkspaceRequests();
    try {
      setOutputDir(await desktopDir());
    } catch {
      setOutputDir("");
    }
    clearOutputState();
    setStatus("出力先をデスクトップに戻しました。");
  }

  async function movePage(offset: number): Promise<void> {
    if (!currentFile) {
      return;
    }
    const nextPage = Math.max(1, Math.min(currentFile.pageCount, currentPage + offset));
    invalidateWorkspaceRequests();
    try {
      await loadPreview(currentFile.path, nextPage);
    } catch (error) {
      setStatus(`ページ移動エラー: ${String(error)}`);
    }
  }

  function addSplitBeforeCurrentPage(): void {
    invalidateWorkspaceRequests();
    if (!currentFile || currentPage <= 1) {
      setStatus("先頭ページの前では分割できません。");
      return;
    }
    clearOutputState();
    updateCurrentPdfSplitPoints((currentPoints) => [...currentPoints, currentPage]);
    setSelectedSplitPoint(currentPage);
    setStatus(`${currentPage}ページの前に分割を追加しました。`);
  }

  function undoLastSplit(): void {
    invalidateWorkspaceRequests();
    if (!currentFile) {
      return;
    }
    clearOutputState();
    updateCurrentPdfSplitPoints((currentPoints) => currentPoints.slice(0, -1));
    setSelectedSplitPoint(null);
    setStatus("最後の分割を取り消しました。");
  }

  function clearCurrentPdfSplits(): void {
    invalidateWorkspaceRequests();
    if (!currentFile || currentPdfSplitPointCount === 0) {
      return;
    }
    if (!window.confirm("現在表示中PDFの分割をすべて解除します。よろしいですか？")) {
      return;
    }
    clearOutputState();
    updateCurrentPdfSplitPoints(() => []);
    setSelectedSegmentKey("");
    setSelectedSplitPoint(null);
    setStatus("現在表示中PDFの分割をすべて解除しました。");
  }

  function deleteSelectedSplitPoint(): void {
    invalidateWorkspaceRequests();
    if (!currentFile) {
      return;
    }
    const targetPoint = selectedSplitPoint ?? (currentSplitPoints.includes(currentPage) ? currentPage : null);
    if (!targetPoint) {
      setStatus("削除対象の分割点を選択してください。");
      return;
    }
    clearOutputState();
    updateCurrentPdfSplitPoints((currentPoints) => currentPoints.filter((point) => point !== targetPoint));
    setSelectedSplitPoint(null);
    setStatus(`${targetPoint}ページ前の分割点を削除しました。`);
  }

  function undoSplitHistory(): void {
    invalidateWorkspaceRequests();
    const last = splitHistory.past.at(-1);
    if (!last) {
      return;
    }
    const file = pdfFiles.find((item) => item.path === last.pdfPath);
    if (!file) {
      return;
    }
    const currentPoints = splitPointsFor(file.pageCount, splitPointsByPdf[last.pdfPath]);
    setSplitHistory((current) => ({
      future: [...current.future, { pdfPath: last.pdfPath, points: currentPoints }],
      past: current.past.slice(0, -1)
    }));
    clearOutputState();
    applySplitPointsForPdf(last.pdfPath, file.pageCount, last.points);
    setSelectedSplitPoint(null);
    setStatus("分割操作を元に戻しました。");
  }

  function redoSplitHistory(): void {
    invalidateWorkspaceRequests();
    const next = splitHistory.future.at(-1);
    if (!next) {
      return;
    }
    const file = pdfFiles.find((item) => item.path === next.pdfPath);
    if (!file) {
      return;
    }
    const currentPoints = splitPointsFor(file.pageCount, splitPointsByPdf[next.pdfPath]);
    setSplitHistory((current) => ({
      future: current.future.slice(0, -1),
      past: [...current.past, { pdfPath: next.pdfPath, points: currentPoints }]
    }));
    clearOutputState();
    applySplitPointsForPdf(next.pdfPath, file.pageCount, next.points);
    setSelectedSplitPoint(null);
    setStatus("分割操作をやり直しました。");
  }

  function mergeSearchResultsByPage(resultsByTerm: Array<{ results: SidecarSearchResult[]; term: string }>): MergedSearchResult[] {
    const byPage = new Map<string, MergedSearchResult>();
    for (const item of resultsByTerm) {
      for (const result of item.results) {
        const key = `${result.pdf_path}#${result.page_no}`;
        const existing =
          byPage.get(key) ??
          ({
            matchedTerms: [],
            pageNo: result.page_no,
            pdfPath: result.pdf_path,
            snippets: [],
            totalCount: 0
          } satisfies MergedSearchResult);
        existing.totalCount += result.count;
        if (!existing.matchedTerms.includes(item.term)) {
          existing.matchedTerms.push(item.term);
        }
        if (result.snippet && !existing.snippets.includes(result.snippet)) {
          existing.snippets.push(result.snippet);
        }
        byPage.set(key, existing);
      }
    }
    return Array.from(byPage.values()).sort((a, b) => a.pageNo - b.pageNo);
  }

  async function loadSearchHighlights(pdfPath: string, pageNo: number, terms = selectedSearchTermValues): Promise<void> {
    const targetTerms = uniqueSearchTerms(terms);
    if (!targetTerms.length) {
      setSearchHighlights([]);
      return;
    }
    if (devPreviewEnabled) {
      setSearchHighlights(
        pdfPath === step2ReviewPdfPath && pageNo === 4
          ? devPreviewSearchHighlights.filter((rect) => targetTerms.includes(rect.term))
          : []
      );
      return;
    }
    try {
      const responses = await Promise.all(
        targetTerms.map(async (term) => {
          const response = await invokeSidecar({
            command: "search_highlights",
            pdf_path: pdfPath,
            page_no: pageNo,
            query: term
          });
          if (!response.ok || response.command !== "search_highlights") {
            throw new Error(response.ok ? "検索ハイライトを取得できませんでした。" : sidecarError(response));
          }
          const result = response as SidecarSearchHighlightsResponse;
          return result.rects.map((rect) => ({ ...rect, term }));
        })
      );
      setSearchHighlights(responses.flat());
    } catch (error) {
      setSearchHighlights([]);
      setStatus(`検索ハイライト取得エラー: ${String(error)}`);
    }
  }

  async function selectSearchResult(result: MergedSearchResult, index: number): Promise<void> {
    const nextHit = { index, pageNo: result.pageNo, pdfPath: result.pdfPath };
    setSelectedSearchHit(nextHit);
    await selectPageForPreview(result.pdfPath, result.pageNo);
    await loadSearchHighlights(result.pdfPath, result.pageNo, result.matchedTerms);
    setStatus(`${basename(result.pdfPath)} の${result.pageNo}ページへ移動しました。`);
  }

  async function selectIndexCandidate(candidate: IndexCandidate): Promise<void> {
    setSelectedSearchHit(null);
    setSearchHighlights([]);
    await selectPageForPreview(candidate.pdf_path, candidate.page_no);
    setStatus(`${basename(candidate.pdf_path)} の${candidate.page_no}ページへ移動しました。`);
  }

  async function runTextSearch(): Promise<void> {
    if (!currentPdf) {
      return;
    }
    const terms = selectedSearchTermValues;
    if (!terms.length) {
      setSearchResults([]);
      setSelectedSearchHit(null);
      setSearchHighlights([]);
      setStatus("用語を選択してください。");
      return;
    }
    if (devPreviewEnabled) {
      setSearchResults(devPreviewSearchResults);
      setSelectedSearchHit({ index: 0, pageNo: 4, pdfPath: step2ReviewPdfPath });
      setSearchHighlights(devPreviewSearchHighlights.filter((rect) => terms.includes(rect.term)));
      setStatus("DEVプレビューの検索結果を表示しました。");
      return;
    }
    try {
      const responses = await Promise.all(
        terms.map(async (term) => {
          const response = await invokeSidecar({
            command: "search_text",
            current_pdf: currentPdf,
            pdf_paths: [currentPdf],
            query: term,
            scope: "current_pdf"
          });
          if (!response.ok || response.command !== "search_text") {
            throw new Error(response.ok ? "検索結果を取得できませんでした。" : sidecarError(response));
          }
          const result = response as SidecarSearchTextResponse;
          return { results: result.results, term };
        })
      );
      const mergedResults = mergeSearchResultsByPage(responses);
      setSearchResults(mergedResults);
      setSelectedSearchHit(null);
      setSearchHighlights([]);
      setStatus(`${mergedResults.length}ページの検索結果を取得しました。`);
    } catch (error) {
      setStatus(`検索エラー: ${String(error)}`);
    }
  }

  async function runIndexCandidateSearch(): Promise<void> {
    if (!currentPdf) {
      return;
    }
    if (devPreviewEnabled) {
      setIndexCandidates(devPreviewIndexCandidates);
      setStatus("DEVプレビューの候補検索結果を表示しました。");
      return;
    }
    try {
      const response = await invokeSidecar({
        command: "index_candidates",
        pdf_paths: [currentPdf]
      });
      if (!response.ok || response.command !== "index_candidates") {
        throw new Error(response.ok ? "候補検索結果を取得できませんでした。" : sidecarError(response));
      }
      const result = response as SidecarIndexCandidatesResponse;
      setIndexCandidates(result.candidates);
      setStatus(`${result.candidates.length}件の候補を取得しました。`);
    } catch (error) {
      setIndexCandidates([]);
      setStatus(`候補検索エラー: ${String(error)}`);
    }
  }

  function changePreviewFitMode(nextMode: PreviewFitMode): void {
    setPreviewFitMode(nextMode);
  }

  function changePreviewZoom(nextZoom: number): void {
    const normalizedZoom = Math.max(0.4, Math.min(2.4, nextZoom));
    setPreviewZoom(normalizedZoom);
    const file = currentFile;
    if (!file) {
      return;
    }
    // スライダーのドラッグ中は sidecar への再レンダリング要求が連続発火して重くなるため、
    // 指を止めてから一度だけ再描画する（デバウンス）。
    if (zoomReloadTimerRef.current) {
      clearTimeout(zoomReloadTimerRef.current);
    }
    const pdfPath = file.path;
    const pageNo = currentPage;
    zoomReloadTimerRef.current = setTimeout(() => {
      zoomReloadTimerRef.current = null;
      previewCache.clearPdf(pdfPath);
      loadPreview(pdfPath, pageNo, normalizedZoom).catch((error) => {
        setStatus(`プレビュー倍率変更エラー: ${String(error)}`);
      });
    }, 180);
  }

  step2KeyHandlerRef.current = (event: KeyboardEvent): void => {
    if (activeStep !== "split" || isEditableKeyboardTarget(event.target)) {
      return;
    }

      if (event.key === "ArrowLeft" && !event.ctrlKey && !event.altKey && !event.metaKey && !event.shiftKey) {
        event.preventDefault();
        void movePage(-1);
        return;
      }
      if (event.key === "ArrowLeft" && event.altKey && !event.ctrlKey && !event.metaKey && !event.shiftKey) {
        event.preventDefault();
        void movePdf(-1);
        return;
      }
      if (event.key === "ArrowRight" && !event.ctrlKey && !event.altKey && !event.metaKey && !event.shiftKey) {
        event.preventDefault();
        void movePage(1);
        return;
      }
      if (event.key === "ArrowRight" && event.altKey && !event.ctrlKey && !event.metaKey && !event.shiftKey) {
        event.preventDefault();
        void movePdf(1);
        return;
      }
      if (event.key === " " && !event.ctrlKey && !event.altKey && !event.metaKey && !event.shiftKey) {
        event.preventDefault();
        addSplitBeforeCurrentPage();
        return;
      }
      if (event.key === "Enter" && event.ctrlKey && !event.altKey && !event.metaKey && !event.shiftKey) {
        event.preventDefault();
        addSplitBeforeCurrentPage();
        return;
      }
      if (event.key.toLowerCase() === "z" && event.ctrlKey && !event.shiftKey && !event.altKey && !event.metaKey) {
        event.preventDefault();
        undoSplitHistory();
        return;
      }
      if (event.key.toLowerCase() === "y" && event.ctrlKey && !event.shiftKey && !event.altKey && !event.metaKey) {
        event.preventDefault();
        redoSplitHistory();
        return;
      }
      if (event.key.toLowerCase() === "u" && event.ctrlKey && event.shiftKey && !event.altKey && !event.metaKey) {
        event.preventDefault();
        undoLastSplit();
        return;
      }
      if (event.key === "Delete" && !event.ctrlKey && !event.shiftKey && !event.altKey && !event.metaKey) {
        event.preventDefault();
        deleteSelectedSplitPoint();
        return;
      }
      if (event.key === "Delete" && event.ctrlKey && event.shiftKey && !event.altKey && !event.metaKey) {
        event.preventDefault();
        clearCurrentPdfSplits();
      }
  };

  step3KeyHandlerRef.current = (event: KeyboardEvent): void => {
    if (activeStep !== "input") {
      return;
    }
      // Ctrl+D（前の行コピー）と F7（未解決ジャンプ）は入力中でも安全なので先に処理する。
      if ((event.key === "d" || event.key === "D") && event.ctrlKey && !event.altKey && !event.metaKey && !event.shiftKey) {
        event.preventDefault();
        copyPreviousSegment();
        return;
      }
      if (event.key === "F7" && !event.ctrlKey && !event.altKey && !event.metaKey) {
        event.preventDefault();
        jumpToUnresolvedSegment(event.shiftKey ? -1 : 1);
        return;
      }
      // ↑/↓のセグメント移動は、入力欄・セレクト操作中は通常のカーソル動作を優先する。
      if (isEditableKeyboardTarget(event.target)) {
        return;
      }
      const isPlain = !event.ctrlKey && !event.altKey && !event.metaKey && !event.shiftKey;
      if (event.key === "ArrowDown" && isPlain) {
        event.preventDefault();
        moveSegmentSelection(1);
      } else if (event.key === "ArrowUp" && isPlain) {
        event.preventDefault();
        moveSegmentSelection(-1);
      }
  };

  // キーボードショートカットはマウント時に1回だけ登録し、ハンドラは ref 経由で常に最新を呼ぶ。
  useEffect(() => {
    const listener = (event: KeyboardEvent): void => {
      step2KeyHandlerRef.current(event);
      step3KeyHandlerRef.current(event);
    };
    window.addEventListener("keydown", listener);
    return () => {
      window.removeEventListener("keydown", listener);
    };
  }, []);

  // セグメント構成が変わったら、空の連番を表示順(PDF単位)で自動補完する。
  // 既存値(手動・採番済み)は変更しないので、保存状態の復元値も保持される。
  useEffect(() => {
    if (allSegments.length) {
      fillEmptySeqByRule();
    }
    // 構成変化時のみ空連番を補完する。fillEmptySeqByRule は意図的に依存から除外（毎レンダー再実行を避ける）。
    // 開始番号の変更は updateSeqStart 側で即時再採番するため、ここで seqStart を追わなくてよい。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [segmentKeysSignature]);

  function moveSegmentSelection(offset: number): void {
    if (!allSegments.length) {
      return;
    }
    const currentIndex = allSegments.findIndex((segment) => segment.key === selectedSegmentKey);
    const baseIndex = currentIndex < 0 ? 0 : currentIndex;
    const nextIndex = Math.max(0, Math.min(allSegments.length - 1, baseIndex + offset));
    const next = allSegments[nextIndex];
    if (next && (next.key !== selectedSegmentKey || currentIndex < 0)) {
      void selectSegmentForPreview(next);
    }
  }

  // 連番(seq)以外（箱No・バインダーNo・追加項目の値）を対象にしたコピー用パッチを作る。
  // 空欄は適用先の入力済み値を黙って消さないようパッチに含めない（誤消去の防止）。
  function copyableMetadataPatch(source: Record<string, string>): Record<string, string> {
    const patch: Record<string, string> = {};
    if (source.box_no) {
      patch.box_no = source.box_no;
    }
    if (source.binder_no) {
      patch.binder_no = source.binder_no;
    }
    for (const def of affixDefs) {
      const value = source[def.key];
      if (value) {
        patch[def.key] = value;
      }
    }
    return patch;
  }

  function copyPreviousSegment(): void {
    if (!selectedSegment) {
      return;
    }
    const index = allSegments.findIndex((segment) => segment.key === selectedSegment.key);
    if (index <= 0) {
      setStatus("前の行がありません。");
      return;
    }
    const patch = copyableMetadataPatch(allSegments[index - 1].metadata);
    invalidateWorkspaceRequests();
    clearOutputState();
    setSegmentMetadata((current) => ({
      ...current,
      [selectedSegment.key]: { ...(current[selectedSegment.key] ?? {}), ...patch }
    }));
    setStatus("前の行をコピーしました（連番は維持）。");
  }

  function applyMetadataToAllSegments(): void {
    if (!selectedSegment || allSegments.length <= 1) {
      return;
    }
    const patch = copyableMetadataPatch(selectedSegment.metadata);
    invalidateWorkspaceRequests();
    clearOutputState();
    setSegmentMetadata((current) => {
      const next = { ...current };
      for (const segment of allSegments) {
        next[segment.key] = { ...(next[segment.key] ?? {}), ...patch };
      }
      return next;
    });
    setStatus("全セグメントへ適用しました（連番は各行を維持）。");
  }

  function jumpToUnresolvedSegment(direction: number): void {
    const total = allSegments.length;
    if (!total) {
      return;
    }
    const currentIndex = allSegments.findIndex((segment) => segment.key === selectedSegmentKey);
    const start = currentIndex < 0 ? (direction > 0 ? -1 : total) : currentIndex;
    for (let step = 1; step <= total; step++) {
      const index = (((start + direction * step) % total) + total) % total;
      const segment = allSegments[index];
      if (missingMetadata(segment.metadata).length > 0) {
        void selectSegmentForPreview(segment);
        return;
      }
    }
    setStatus("未入力のセグメントはありません。");
  }

  function updateCommonMetadata(key: "box_no" | "binder_no", value: string): void {
    invalidateWorkspaceRequests();
    clearOutputState();
    setCommonMetadata((current) => ({ ...current, [key]: value }));
  }

  function updateMetadata(segment: SegmentView, key: string, value: string): void {
    invalidateWorkspaceRequests();
    clearOutputState();
    setSegmentMetadata((current) => ({
      ...current,
      [segment.key]: {
        ...(current[segment.key] ?? {}),
        [key]: value
      }
    }));
  }

  // 連番ルール(開始番号 seqStart)に従い、PDF単位で表示順に採番する。
  // onlyEmpty=true なら空のseqだけ補完、false なら手動上書き(manualSeqKeysRef)以外を再採番する。
  function numberSegmentsPerPdf(current: SegmentMetadata, onlyEmpty: boolean, start: number = seqStart): SegmentMetadata {
    const next = { ...current };
    const positionByPdf = new Map<string, number>();
    let changed = false;
    for (const segment of allSegments) {
      const position = positionByPdf.get(segment.pdfPath) ?? 0;
      positionByPdf.set(segment.pdfPath, position + 1);
      const storedSeq = next[segment.key]?.seq ?? "";
      if (onlyEmpty && storedSeq.trim()) {
        continue;
      }
      if (!onlyEmpty && manualSeqKeysRef.current.has(segment.key)) {
        continue;
      }
      const value = String(start + position);
      if (storedSeq === value) {
        continue;
      }
      next[segment.key] = { ...(next[segment.key] ?? {}), seq: value };
      changed = true;
    }
    return changed ? next : current;
  }

  function resequence(): void {
    invalidateWorkspaceRequests();
    clearOutputState();
    setSegmentMetadata((current) => numberSegmentsPerPdf(current, false));
    setStatus("連番を再採番しました（PDF単位・手動入力は保持）。");
  }

  function fillEmptySeqByRule(): void {
    setSegmentMetadata((current) => numberSegmentsPerPdf(current, true));
  }

  function updateSeqStart(value: string): void {
    const parsed = Number(value);
    const nextStart = Number.isFinite(parsed) ? Math.max(1, Math.trunc(parsed)) : 1;
    setSeqStart(nextStart);
    invalidateWorkspaceRequests();
    clearOutputState();
    // 開始番号を変えたら即座に再採番（手動上書きは保持）。新しい値を直接渡す。
    setSegmentMetadata((current) => numberSegmentsPerPdf(current, false, nextStart));
  }

  function updateSeqDigits(value: string): void {
    setSeqDigits(coerceSeqDigits(value));
    invalidateWorkspaceRequests();
    clearOutputState();
  }

  function addAffixDef(): void {
    invalidateWorkspaceRequests();
    clearOutputState();
    setAffixDefs((current) => {
      if (current.length >= MAX_AFFIX_COUNT) {
        return current;
      }
      const used = new Set(current.map((def) => def.key));
      const key = ["affix1", "affix2"].find((candidate) => !used.has(candidate)) ?? `affix_${current.length + 1}`;
      return [...current, { key, label: "", position: "suffix" }];
    });
  }

  function updateAffixDef(key: string, patch: Partial<AffixDef>): void {
    invalidateWorkspaceRequests();
    clearOutputState();
    setAffixDefs((current) => current.map((def) => (def.key === key ? { ...def, ...patch } : def)));
  }

  function removeAffixDef(key: string): void {
    invalidateWorkspaceRequests();
    clearOutputState();
    setAffixDefs((current) => current.filter((def) => def.key !== key));
  }

  // 追加項目の値はセグメント個別（box_no等と同じ二層）。選択中セグメントの metadata へ書き込む。
  // OCR本文から「フォーカス先行・クリック転記」する際の転記先となる追加項目キー。
  function armTranscribeTarget(key: string): void {
    setTranscribeTargetKey(key);
  }

  function clearTranscribeTarget(): void {
    setTranscribeTargetKey("");
  }

  function transcribeSelectionToTarget(): void {
    if (!selectedSegment || !transcribeTargetKey) {
      return;
    }
    const selected = typeof window !== "undefined" ? window.getSelection()?.toString() ?? "" : "";
    // OCR選択には改行・全角空白が混じりやすい。連続空白を1つに畳み、前後を除去してから転記する。
    const cleaned = selected.replace(/[\s　]+/g, " ").trim();
    if (!cleaned) {
      setStatus("OCR本文を選択してから転記してください。");
      return;
    }
    updateMetadata(selectedSegment, transcribeTargetKey, cleaned);
    setStatus("追加項目へ転記しました。");
  }

  function requestSegments(): SidecarSegment[] {
    return allSegments.map((segment) => ({
      pdf_path: segment.pdfPath,
      start_page: segment.startPage,
      end_page: segment.endPage,
      metadata: segment.metadata
    }));
  }

  async function runPreflight(): Promise<void> {
    if (preflightInFlightRef.current) {
      return;
    }
    preflightInFlightRef.current = true;
    setIsPreflighting(true);
    try {
      const response = await invokeSidecar({
        command: "preflight",
        output_dir: outputDir,
        segments: requestSegments(),
        affix_defs: affixDefs,
        seq_digits: seqDigits
      });
      if (response.command !== "preflight") {
        throw new Error(response.ok ? "出力前チェックに失敗しました。" : sidecarError(response));
      }
      const result = response as SidecarPreflightResponse;
      setPreflightChecks(result.checks);
      setExportResult(null);
      setStatus(result.can_run ? "出力できます。" : "修正が必要な項目があります。");
      setActiveStep("output");
    } catch (error) {
      setStatus(`出力前チェックエラー: ${String(error)}`);
    } finally {
      preflightInFlightRef.current = false;
      setIsPreflighting(false);
    }
  }

  async function runExport(): Promise<void> {
    if (exportInFlightRef.current) {
      return;
    }
    exportInFlightRef.current = true;
    setIsExporting(true);
    try {
      const response = await invokeSidecar({
        command: "export",
        output_dir: outputDir,
        segments: requestSegments(),
        affix_defs: affixDefs,
        seq_digits: seqDigits
      });
      if (response.command !== "export") {
        throw new Error(response.ok ? "出力に失敗しました。" : sidecarError(response));
      }
      const result = response as SidecarExportResponse;
      setExportResult(result);
      setPreflightChecks(result.items);
      setStatus(result.ok ? "出力が完了しました。" : "出力結果を確認してください。");
    } catch (error) {
      setStatus(`出力エラー: ${String(error)}`);
    } finally {
      exportInFlightRef.current = false;
      setIsExporting(false);
    }
  }

  async function saveState(): Promise<void> {
    const state: AppPersistedState = {
      version: 1,
      input_paths: pdfFiles.map((file) => file.path),
      output_dir: outputDir,
      split_points_by_pdf: splitPointsByPdf,
      segment_metadata: segmentMetadata,
      common_metadata: commonMetadata,
      affix_defs: affixDefs,
      seq_start: seqStart,
      seq_digits: seqDigits,
      manual_seq_keys: [...manualSeqKeysRef.current],
      current_pdf: currentPdf,
      current_page: currentPage
    };
    const response = await invokeSidecar({ command: "state_save", state });
    setStatus(response.ok ? "状態を保存しました。" : `状態保存エラー: ${sidecarError(response)}`);
  }

  async function loadState(): Promise<void> {
    const requestId = workspaceRequestGateRef.current.next();
    invalidatePreviewRequests();
    const response = await invokeSidecar({ command: "state_load" });
    if (!workspaceRequestGateRef.current.isCurrent(requestId)) {
      return;
    }
    if (!response.ok || response.command !== "state_load") {
      setStatus(response.ok ? "状態読込に失敗しました。" : `状態読込エラー: ${sidecarError(response)}`);
      return;
    }
    const state = response.state as Partial<AppPersistedState>;
    if (!Array.isArray(state.input_paths) || !state.input_paths.length) {
      setStatus("保存済み状態はありません。");
      return;
    }
    const missingInputPaths = response.missing_input_paths ?? [];
    const hasMissingInputPdf = response.messages?.includes("missing_input_pdf") || missingInputPaths.length > 0;
    try {
      const inputPathsToRestore = restorableInputPaths(state.input_paths, missingInputPaths);
      const loaded = await Promise.all(inputPathsToRestore.map((path) => loadPdfInfo(path)));
      if (!workspaceRequestGateRef.current.isCurrent(requestId)) {
        return;
      }
      const restoreDecision = resolveMissingSavedPdfRestore({
        currentPage: state.current_page,
        currentPdf: state.current_pdf,
        hasMissingInputPdf,
        loadedPdfFiles: loaded,
        missingInputPaths,
        savedInputPaths: state.input_paths
      });
      previewCache.clear();
      loadedThumbnailKeysRef.current.clear();
      setPdfFiles(loaded);
      setOutputDir(state.output_dir || outputDir);
      setSplitPointsByPdf(state.split_points_by_pdf ?? {});
      setSegmentMetadata(state.segment_metadata ?? {});
      setCommonMetadata({ ...defaultCommonMetadata, ...(state.common_metadata ?? {}) });
      setAffixDefs(Array.isArray(state.affix_defs) ? state.affix_defs : []);
      setSeqStart(typeof state.seq_start === "number" ? Math.max(1, Math.trunc(state.seq_start)) : 1);
      setSeqDigits(coerceSeqDigits(state.seq_digits));
      manualSeqKeysRef.current = new Set(Array.isArray(state.manual_seq_keys) ? state.manual_seq_keys : []);
      setCurrentPdf(restoreDecision.currentPdf);
      setCurrentPage(restoreDecision.currentPage);
      if (!restoreDecision.shouldLoadPreview) {
        setSelectedSegmentKey("");
        setPreviewDataUrl("");
      }
      clearOutputState();
      if (restoreDecision.shouldLoadPreview) {
        await loadPreview(restoreDecision.currentPdf, restoreDecision.currentPage);
      }
      if (!workspaceRequestGateRef.current.isCurrent(requestId)) {
        return;
      }
      setStatus(restoreDecision.statusText);
    } catch (error) {
      if (!workspaceRequestGateRef.current.isCurrent(requestId)) {
        return;
      }
      setStatus(`状態復元エラー: ${String(error)}`);
    }
  }

  const statusTone = status.includes("エラー")
    ? "danger"
    : status.includes("修正") || status.includes("不足") || status.includes("再選択")
      ? "warning"
      : status.includes("完了") || status.includes("できます")
        ? "ok"
        : "";
  const updateTone =
    updateState === "error"
      ? "danger"
      : updateState === "available" || updateState === "installing"
        ? "warning"
        : updateState === "current" || updateState === "installed"
          ? "ok"
          : "";
  const activeStepIndex = steps.findIndex((step) => step.id === activeStep);
  const activeStepMeta = steps[activeStepIndex] ?? steps[0];
  const ActiveStepIcon = activeStepMeta.icon;
  const splitHeaderSummary =
    activeStep === "split"
      ? [
          { label: "表示PDF", value: currentFile ? basename(currentFile.path) : "未選択" },
          { label: "ページ位置", value: currentFile ? `${currentPage} / ${currentFile.pageCount}` : "-" },
          { label: "セグメント", value: `${allSegments.length}件` },
          { label: "選択範囲", value: currentVisibleSegment?.pages ?? "-" }
        ]
      : null;

  function renderImportList() {
    return (
      <div className="pane stack">
        <PaneHeader
          title="PDF一覧"
          description={pdfFiles.length ? `${pdfFiles.length}件 / ${totalPages}ページ` : "処理対象PDFを追加します。"}
          action={
            <button className="ghost danger" disabled={!pdfFiles.length} onClick={clearPdfSelection} type="button">
              <IconLabel icon={Trash2}>全クリア</IconLabel>
            </button>
          }
        />
        {pdfFiles.length ? (
          <div className="queue-list">
            {pdfFiles.map((file) => (
              <div className={file.path === currentPdf ? "queue-row selected" : "queue-row"} key={file.path}>
                <button className="queue-main" onClick={() => void selectPdf(file.path)} type="button">
                  <strong>{basename(file.path)}</strong>
                  <small>{file.pageCount}ページ</small>
                  <span>{file.path}</span>
                </button>
                <button
                  aria-label={`${basename(file.path)} を一覧から外す`}
                  className="icon-button danger"
                  onClick={() => void removePdf(file.path)}
                  type="button"
                >
                  <XCircle aria-hidden="true" size={17} />
                </button>
              </div>
            ))}
          </div>
        ) : (
          <EmptyState
            action={
              <button className="primary" onClick={choosePdfs} type="button">
                <IconLabel icon={Upload}>PDFを選択</IconLabel>
              </button>
            }
            icon={FileText}
            title="PDFが未選択です"
          >
            最初に処理対象のPDFを追加します。
          </EmptyState>
        )}
      </div>
    );
  }

  function renderSplitList() {
    return (
      <div className="pane split-list stack">
        <PaneHeader
          title="分割対象"
          description={currentFile ? `${basename(currentFile.path)} / ${currentPage}ページ目を表示中` : "PDF未選択"}
          action={
            <button
              aria-keyshortcuts="Control+Shift+Delete"
              className="ghost danger split-list-reset"
              disabled={!currentFile || currentPdfSplitPointCount === 0}
              onClick={clearCurrentPdfSplits}
              title="現在表示中PDFの分割を全解除 (Ctrl+Shift+Delete)"
              type="button"
            >
              <IconLabel icon={XCircle}>分割を全解除</IconLabel>
            </button>
          }
        />
        {pdfFiles.length ? (
          <div className="compact-group">
            <span className="group-label">PDF</span>
            <div className="queue-list slim">
              {pdfFiles.map((file) => (
                <button
                  className={file.path === currentPdf ? "list-row selected" : "list-row"}
                  key={file.path}
                  onClick={() => void selectPdf(file.path)}
                  type="button"
                >
                  <span>
                    <strong>{basename(file.path)}</strong>
                    <small>{file.pageCount}ページ</small>
                  </span>
                </button>
              ))}
            </div>
          </div>
        ) : null}
        <div className="compact-group">
          <span className="group-label">ページ状態一覧</span>
          <div className="page-state-list">
            {currentPageStates.length ? (
              currentPageStates.map((page) => {
                const rowClassName = [
                  "page-state-row",
                  page.isCurrent ? "selected" : "",
                  page.segment?.key === currentVisibleSegment?.key ? "current-page-range" : "",
                  page.hasSplitBefore ? "split-before" : "",
                  selectedSplitPoint === page.pageNo ? "split-selected" : ""
                ]
                  .filter(Boolean)
                  .join(" ");
                return (
                  <button
                    className={rowClassName}
                    key={`${currentPdf}-${page.pageNo}`}
                    onClick={() => void selectPageForPreview(currentPdf, page.pageNo)}
                    type="button"
                  >
                    <span className="page-thumb mini">
                      {page.thumbnail ? <img alt="" src={page.thumbnail} /> : <span>{page.pageNo}</span>}
                    </span>
                    <span className="page-state-main">
                      <strong>{page.pageNo}ページ</strong>
                      <small>{page.segment ? `${page.segment.startPage}-${page.segment.endPage}` : "-"}</small>
                    </span>
                    <span className="page-state-flags">
                      {page.hasSplitBefore ? (
                        <span
                          aria-label={`${page.pageNo}ページ前の分割点を選択`}
                          className="split-marker"
                          onClick={(event) => {
                            event.stopPropagation();
                            setSelectedSplitPoint(page.pageNo);
                          }}
                          role="button"
                          tabIndex={0}
                        >
                          分割
                        </span>
                      ) : null}
                      {typeof page.blankScore === "number" ? <span className="blank-marker">白紙</span> : null}
                    </span>
                  </button>
                );
              })
            ) : (
              <EmptyState icon={Split} title="ページなし">
                PDFを選択するとページ状態一覧が表示されます。
              </EmptyState>
            )}
          </div>
        </div>
      </div>
    );
  }

  function renderInputList() {
    return (
      <div className="pane stack">
        <PaneHeader
          title="セグメント一覧"
          description={`${readySegments}件 OK / ${incompleteSegments}件 未入力　（↑↓で移動）`}
        />
        {allSegments.length ? (
          <>
            <div className="action-row">
              <button
                disabled={!incompleteSegments}
                onClick={() => jumpToUnresolvedSegment(1)}
                title="次の未入力セグメントへ (F7 / Shift+F7で前へ)"
                type="button"
              >
                <IconLabel icon={ArrowRight}>次の未解決 (F7)</IconLabel>
              </button>
            </div>
            <div className="mini-table">
              <div className="mini-head">
                <span>範囲</span>
                <span>命名</span>
                <span>状態</span>
              </div>
            {allSegments.map((segment) => {
              const missing = missingMetadata(segment.metadata);
              return (
                <button
                  className={segment.key === selectedSegment?.key ? "mini-row selected" : "mini-row"}
                  key={segment.key}
                  onClick={() => void selectSegmentForPreview(segment)}
                  type="button"
                >
                  <span>
                    <strong>{segment.pages}</strong>
                    <small>{basename(segment.pdfPath)}</small>
                  </span>
                  <span>{`${segment.metadata.box_no || "-"} / ${segment.metadata.binder_no || "-"} / ${
                    segment.metadata.seq || "-"
                  }`}</span>
                  <span className={missing.length ? "state-text warning" : "state-text ok"}>
                    {missing.length ? "未入力" : "OK"}
                  </span>
                </button>
              );
            })}
            </div>
          </>
        ) : (
          <EmptyState icon={PencilLine} title="入力対象がありません">
            PDFを取込み、分割を確認してから入力します。
          </EmptyState>
        )}
      </div>
    );
  }

  function renderOutputList() {
    return (
      <div className="pane stack">
        <PaneHeader
          title="出力予定"
          description={preflightChecks.length ? `${preflightChecks.length}件` : "出力前チェック待ち"}
        />
        {preflightChecks.length ? (
          <div className="output-list">
            {preflightChecks.map((check, index) => (
              <div
                className={isOutputCheckOk(check) ? "output-row" : "output-row error"}
                key={`${check.pdf_path}-${check.pages}-${index}`}
              >
                <span>
                  <strong>{check.filename || check.requested_filename || "-"}</strong>
                  <small>{basename(check.pdf_path)} / {check.pages}ページ</small>
                </span>
                <span className={isOutputCheckOk(check) ? "state-text ok" : "state-text warning"}>
                  {outputListStateText(check)}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <EmptyState
            action={
              <button disabled={!canRunPreflight || isPreflighting} onClick={runPreflight} type="button">
                <IconLabel icon={ClipboardCheck}>出力前チェック</IconLabel>
              </button>
            }
            icon={Download}
            title="未確認です"
          >
            入力内容が揃ったら、ここで出力可否を確認します。
          </EmptyState>
        )}
      </div>
    );
  }

  function renderLeftPane() {
    if (activeStep === "import") {
      return renderImportList();
    }
    if (activeStep === "split") {
      return renderSplitList();
    }
    if (activeStep === "input") {
      return renderInputList();
    }
    return renderOutputList();
  }

  function renderImportWork() {
    return (
      <section className="work-card import-work stack" aria-label="PDF取込">
        <PaneHeader title="取込設定" description="対象PDF、出力先、共通項目をここで揃えます。" />
        <div className="workbench-checks" aria-label="取込完了条件">
          <StatusCheck ok={pdfFiles.length > 0} label="PDF" detail={pdfFiles.length ? `${pdfFiles.length}件 / ${totalPages}ページ` : "未選択"} />
          <StatusCheck ok={Boolean(outputDir)} label="出力先" detail={outputDir || "未設定"} />
          <StatusCheck
            ok={Boolean(commonMetadata.box_no && commonMetadata.binder_no)}
            label="共通項目"
            detail={`箱 ${commonMetadata.box_no || "-"} / バインダー ${commonMetadata.binder_no || "-"}`}
          />
        </div>
        <div className="import-section-grid">
          <div className="setting-block primary-block">
            <div className="setting-block-header">
              <span className="section-label">対象PDF</span>
              <strong>{pdfFiles.length ? `${pdfFiles.length}件 / ${totalPages}ページ` : "未選択"}</strong>
            </div>
            <div className="action-row import-actions">
              <button className="primary" onClick={choosePdfs} type="button">
                <IconLabel icon={Upload}>PDFを選択</IconLabel>
              </button>
              <button className="ghost danger" disabled={!pdfFiles.length} onClick={clearPdfSelection} type="button">
                <IconLabel icon={Trash2}>全クリア</IconLabel>
              </button>
            </div>
          </div>

          <div className="setting-block">
            <div className="setting-block-header">
              <span className="section-label">出力先</span>
              <strong>{outputDir ? "設定済み" : "未設定"}</strong>
            </div>
            <div className="action-row import-actions">
              <button onClick={chooseOutputDir} type="button">
                <IconLabel icon={FolderOpen}>出力フォルダ</IconLabel>
              </button>
              <button disabled={!outputDir} onClick={() => void resetOutputDir()} type="button">
                <IconLabel icon={XCircle}>デスクトップへ戻す</IconLabel>
              </button>
            </div>
            <p className="path-line">{outputDir || "出力先はまだ選択されていません。"}</p>
          </div>

          <div className="setting-block">
            <div className="setting-block-header">
              <span className="section-label">共通項目</span>
              <strong>{commonMetadata.box_no || commonMetadata.binder_no ? "初期値あり" : "任意"}</strong>
            </div>
            <div className="field-grid two">
              <label>
                箱No
                <input value={commonMetadata.box_no} onChange={(event) => updateCommonMetadata("box_no", event.target.value)} />
              </label>
              <label>
                バインダーNo
                <input
                  value={commonMetadata.binder_no}
                  onChange={(event) => updateCommonMetadata("binder_no", event.target.value)}
                />
              </label>
            </div>
          </div>
        </div>
        <div className="workbench-footer">
          <div className="aux-actions" aria-label="補助操作">
            <button onClick={loadState} type="button">
              <IconLabel icon={RotateCcw}>状態を復元</IconLabel>
            </button>
            <button onClick={saveState} type="button">
              <IconLabel icon={Save}>状態を保存</IconLabel>
            </button>
          </div>
          <button className="primary wide" disabled={!canContinueFromImport} onClick={() => setActiveStep("split")} type="button">
            <IconLabel icon={ChevronRight}>分割へ進む</IconLabel>
          </button>
        </div>
      </section>
    );
  }

  function renderPreviewToolbar() {
    return (
      <div className="preview-toolbar" aria-label="プレビュー操作">
        <div className="split-control-group page-jump">
            <span className="control-label">ページ番号</span>
            <div className="action-row">
              <input
                aria-label="ページ番号"
                disabled={!currentFile}
                max={currentFile?.pageCount ?? 1}
                min={1}
                onChange={(event) => void selectPageForPreview(currentPdf, Number(event.target.value) || 1)}
                type="number"
                value={currentPage}
              />
              <span className="page-total">/ {currentFile?.pageCount ?? "-"}</span>
            </div>
          </div>
          <div className="split-control-group">
            <span className="control-label">ページ移動</span>
            <div className="action-row">
              <button
                aria-keyshortcuts="ArrowLeft"
                disabled={!currentFile || currentPage <= 1}
                onClick={() => void movePage(-1)}
                title="前ページ (←)"
                type="button"
              >
                <IconLabel icon={ArrowLeft}>前ページ</IconLabel>
              </button>
              <button
                aria-keyshortcuts="ArrowRight"
                disabled={!currentFile || currentPage >= (currentFile?.pageCount ?? 1)}
                onClick={() => void movePage(1)}
                title="次ページ (→)"
                type="button"
              >
                <IconLabel icon={ArrowRight}>次ページ</IconLabel>
              </button>
            </div>
          </div>
          <div className="split-control-group zoom-controls">
            <span className="control-label">表示</span>
            <div className="action-row">
              <button
                className={previewFitMode === "width" ? "selected" : ""}
                disabled={!currentFile}
                onClick={() => changePreviewFitMode("width")}
                type="button"
              >
                幅合わせ
              </button>
              <button
                className={previewFitMode === "page" ? "selected" : ""}
                disabled={!currentFile}
                onClick={() => changePreviewFitMode("page")}
                type="button"
              >
                全体表示
              </button>
              <button
                className={previewFitMode === "free" ? "selected" : ""}
                disabled={!currentFile}
                onClick={() => changePreviewFitMode("free")}
                title="手動ズーム（実寸）"
                type="button"
              >
                実寸
              </button>
              <input
                aria-label="ズーム倍率"
                disabled={!currentFile}
                max={2.4}
                min={0.4}
                onChange={(event) => {
                  changePreviewFitMode("free");
                  void changePreviewZoom(Number(event.target.value));
                }}
                step={0.1}
                type="range"
                value={previewZoom}
              />
              <strong>{Math.round(previewZoom * 100)}%</strong>
            </div>
          </div>
        </div>
    );
  }

  function renderPreviewFrame() {
    const previewClassName = `preview-frame ${previewFitMode}`;
    return (
      <div className={previewClassName}>
        {previewDataUrl ? (
            <div className="preview-page-layer">
              <img alt="PDFページプレビュー" src={previewDataUrl} />
              {searchHighlights.length ? (
                <div className="search-highlight-layer" aria-hidden="true">
                  {searchHighlights.map((rect, index) => (
                    <span
                      className="search-highlight-rect"
                      data-term={rect.term}
                      key={`${rect.term}-${rect.x0}-${rect.y0}-${index}`}
                      title={rect.term}
                      style={{
                        height: `${((rect.y1 - rect.y0) / rect.page_height) * 100}%`,
                        left: `${(rect.x0 / rect.page_width) * 100}%`,
                        top: `${(rect.y0 / rect.page_height) * 100}%`,
                        width: `${((rect.x1 - rect.x0) / rect.page_width) * 100}%`
                      }}
                    />
                  ))}
                </div>
              ) : null}
            </div>
          ) : (
            <EmptyState icon={FileText} title="プレビューなし">
              PDFを選択するとページプレビューを表示します。
            </EmptyState>
          )}
        </div>
    );
  }

  function renderOcrTextPanel() {
    const targetIndex = affixDefs.findIndex((def) => def.key === transcribeTargetKey);
    const targetDef = targetIndex >= 0 ? affixDefs[targetIndex] : null;
    const transcribeArmed = Boolean(targetDef && selectedSegment);
    return (
      <div className="legacy-panel-section assist-section ocr-text-panel">
        <span className="group-label">OCRテキスト</span>
        <small>{pageTextStatus}</small>
        {transcribeArmed && targetDef ? (
          <div className="ocr-transcribe-bar" role="status">
            <span>
              選択を「追加項目{targetIndex + 1}（{targetDef.position === "prefix" ? "先頭" : "末尾"}）」へ
            </span>
            <button
              className="primary"
              onMouseDown={(event) => event.preventDefault()}
              onClick={transcribeSelectionToTarget}
              type="button"
            >
              転記
            </button>
            <button className="ghost" onClick={clearTranscribeTarget} type="button">
              解除
            </button>
          </div>
        ) : null}
        <div
          className="ocr-text-scroll"
          aria-label="OCRテキスト"
          tabIndex={transcribeArmed ? 0 : -1}
          onKeyDown={(event) => {
            if (!transcribeArmed) {
              return;
            }
            if (event.key === "Enter") {
              event.preventDefault();
              transcribeSelectionToTarget();
            } else if (event.key === "Escape") {
              event.preventDefault();
              clearTranscribeTarget();
            }
          }}
        >
          {renderHighlightedOcrText()}
        </div>
      </div>
    );
  }

  function renderSplitWork() {
    return (
      <section className="work-card split-work stack" aria-label="分割">
        {renderPreviewToolbar()}
        {renderPreviewFrame()}
      </section>
    );
  }

  function renderInputWork() {
    return (
      <section className="work-card split-work input-work stack" aria-label="入力プレビュー">
        {renderPreviewToolbar()}
        {renderPreviewFrame()}
      </section>
    );
  }

  function renderAffixDefsSection() {
    const affixExpanded = affixExpandedOverride ?? affixDefs.length > 0;
    const handleAddAffix = () => {
      setAffixExpandedOverride(true);
      addAffixDef();
    };
    return (
      <div className="legacy-panel-section affix-defs-section">
        <div className="affix-defs-head">
          <button
            className="accordion-trigger"
            aria-controls="affix-defs-body"
            aria-expanded={affixExpanded}
            onClick={() => setAffixExpandedOverride(!affixExpanded)}
            type="button"
          >
            <ChevronRight aria-hidden="true" className="accordion-chevron" data-open={affixExpanded} size={14} />
            <span className="group-label">追加項目</span>
            <span className="accordion-count">{affixDefs.length}件</span>
          </button>
          <button
            className="ghost"
            disabled={affixDefs.length >= MAX_AFFIX_COUNT}
            onClick={handleAddAffix}
            type="button"
          >
            <IconLabel icon={Plus}>追加</IconLabel>
          </button>
        </div>
        <div id="affix-defs-body" className="affix-defs-body" hidden={!affixExpanded}>
          {affixDefs.length ? (
            <div className="affix-def-list">
              {affixDefs.map((def, index) => (
                <div className="affix-def-row" key={def.key}>
                  <input
                    aria-label={`追加項目${index + 1}の値`}
                    className={transcribeTargetKey === def.key ? "affix-value-input transcribe-armed" : "affix-value-input"}
                    disabled={!selectedSegment}
                    placeholder={selectedSegment ? "値（例: ヨシダ商事）" : "セグメントを選択"}
                    value={selectedSegment?.metadata[def.key] ?? ""}
                    onChange={(event) => selectedSegment && updateMetadata(selectedSegment, def.key, event.target.value)}
                    onFocus={() => armTranscribeTarget(def.key)}
                  />
                  <select
                    aria-label={`追加項目${index + 1}の挿入位置`}
                    value={def.position}
                    onChange={(event) => updateAffixDef(def.key, { position: event.target.value as AffixDef["position"] })}
                  >
                    {AFFIX_POSITIONS.map((position) => (
                      <option key={position} value={position}>
                        {position === "prefix" ? "先頭" : "末尾"}
                      </option>
                    ))}
                  </select>
                  <button
                    aria-label={`追加項目${index + 1}を削除`}
                    className="ghost danger"
                    onClick={() => removeAffixDef(def.key)}
                    type="button"
                  >
                    <Trash2 aria-hidden="true" size={16} />
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <small className="muted-line">会社名・契約書名など、先頭/末尾に挿入する項目を追加できます。</small>
          )}
        </div>
      </div>
    );
  }

  function renderInputControls() {
    return (
      <aside className="right-panel legacy-split-right input-controls stack" aria-label="STEP3命名入力">
        <PaneHeader
          title="命名入力"
          description={
            selectedSegment
              ? `${basename(selectedSegment.pdfPath)} / ${selectedSegment.pages}ページ`
              : "分割セグメントがありません。"
          }
        />
        <div className="filename-preview">
          <span>出力名プレビュー</span>
          <strong>{selectedSegment ? previewFilename(selectedSegment.metadata, affixDefs, seqDigits) : "-"}</strong>
        </div>
        {selectedSegment ? (
          <div className="legacy-panel-section">
            <span className="group-label">命名項目</span>
            <div className="field-grid three">
              <label>
                箱No
                <input
                  value={selectedSegment.metadata.box_no}
                  onChange={(event) => updateMetadata(selectedSegment, "box_no", event.target.value)}
                />
              </label>
              <label>
                バインダーNo
                <input
                  value={selectedSegment.metadata.binder_no}
                  onChange={(event) => updateMetadata(selectedSegment, "binder_no", event.target.value)}
                />
              </label>
              <label>
                連番
                <input
                  value={selectedSegment.metadata.seq}
                  onChange={(event) => {
                    manualSeqKeysRef.current.add(selectedSegment.key);
                    updateMetadata(selectedSegment, "seq", event.target.value);
                  }}
                />
              </label>
            </div>
            <details className="seq-rule-accordion">
              <summary className="accordion-summary">
                <ChevronRight aria-hidden="true" className="accordion-chevron" size={14} />
                <span className="control-label">連番ルール</span>
                <span className="accordion-summary-value">開始 {seqStart} / {seqDigits}桁</span>
              </summary>
              <div className="seq-rule">
                <div className="seq-rule-fields">
                  <label>
                    開始番号
                    <input
                      min={1}
                      type="number"
                      value={seqStart}
                      onChange={(event) => updateSeqStart(event.target.value)}
                    />
                  </label>
                  <label>
                    桁数
                    <input
                      max={MAX_SEQ_DIGITS}
                      min={MIN_SEQ_DIGITS}
                      type="number"
                      value={seqDigits}
                      onChange={(event) => updateSeqDigits(event.target.value)}
                    />
                  </label>
                </div>
                <small className="muted-line">PDFごとに開始番号から自動採番（{seqDigits}桁ゼロ埋め）。手動入力は再採番でも保持。</small>
              </div>
            </details>
            <div className="action-row">
              <button className="primary" disabled={!allSegments.length} onClick={resequence} type="button">
                <IconLabel icon={ClipboardCheck}>連番を再採番</IconLabel>
              </button>
              <button
                disabled={allSegments.findIndex((segment) => segment.key === selectedSegment.key) <= 0}
                onClick={copyPreviousSegment}
                title="前の行をコピー (Ctrl+D)・連番は維持"
                type="button"
              >
                <IconLabel icon={Copy}>前の行をコピー</IconLabel>
              </button>
              <button
                disabled={allSegments.length <= 1}
                onClick={applyMetadataToAllSegments}
                title="この内容を全セグメントへ適用（連番は各行を維持）"
                type="button"
              >
                <IconLabel icon={ListChecks}>一括適用</IconLabel>
              </button>
            </div>
          </div>
        ) : (
          <EmptyState icon={PencilLine} title="入力対象がありません">
            分割セグメントを作成してから入力します。
          </EmptyState>
        )}
        {renderAffixDefsSection()}
        {renderOcrTextPanel()}
        <div className="legacy-panel-section completion-section">
          <div className="workbench-checks compact" aria-label="入力完了条件">
            <StatusCheck ok={allSegments.length > 0} label="入力対象" detail={`${allSegments.length}件`} />
            <StatusCheck ok={!incompleteSegments && allSegments.length > 0} label="未入力" detail={`${incompleteSegments}件`} />
            <StatusCheck ok={Boolean(outputDir)} label="出力先" detail={outputDir || "未設定"} />
          </div>
          <button className="primary wide" disabled={!canRunPreflight || isPreflighting} onClick={runPreflight} type="button">
            <IconLabel icon={ChevronRight}>出力前チェック</IconLabel>
          </button>
        </div>
      </aside>
    );
  }

  function renderOutputWork() {
    return (
      <section className="work-card stack" aria-label="出力">
        <PaneHeader
          title="出力確認"
          description={preflightChecks.length ? `${preflightChecks.length}件の出力予定` : "出力前チェック待ち"}
        />
        <div className="summary-strip">
          <StatLine label="要修正" value={`${outputIssues}件`} />
          <StatLine label="既存あり" value={`${existingOutputs}件`} />
          <StatLine label="出力先" value={outputDir || "未設定"} />
        </div>
        {exportResult ? (
          <div className="log-box">
            <strong>出力結果</strong>
            <p>{`作成 ${exportResult.summary.created}件 / 失敗 ${exportResult.summary.failed}件`}</p>
            {exportResult.messages && exportResult.messages.length > 0 ? (
              <ul className="export-messages">
                {exportResult.messages.map((msg) => (
                  <li key={msg}>{formatTopLevelMessage(msg)}</li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : null}
        {preflightChecks.length ? (
          <div className="check-table">
            <div className="check-head">
              <span>ページ</span>
              <span>予定ファイル名</span>
              <span>既存</span>
              <span>状態</span>
            </div>
            {preflightChecks.map((check, index) => (
              <div
                className={isOutputCheckOk(check) ? "check-row" : "check-row error"}
                key={`${check.pdf_path}-${check.pages}-${index}`}
              >
                <span>{check.pages}</span>
                <span>{check.filename || check.requested_filename || "-"}</span>
                <span>{check.has_existing_output ? "あり" : "なし"}</span>
                <span>{outputDetailStateText(check)}</span>
              </div>
            ))}
          </div>
        ) : (
          <EmptyState icon={Download} title="出力前チェック待ちです">
            入力内容が揃ったら、ここで出力可否を確認します。
          </EmptyState>
        )}
        <div className="workbench-footer">
          <button disabled={!canRunPreflight || isPreflighting} onClick={runPreflight} type="button">
            <IconLabel icon={ClipboardCheck}>再チェック</IconLabel>
          </button>
          <button className="primary wide" disabled={!canExport || isExporting} onClick={runExport} type="button">
            <IconLabel icon={Download}>出力実行</IconLabel>
          </button>
        </div>
      </section>
    );
  }

  function renderWorkPane() {
    if (activeStep === "import") {
      return renderImportWork();
    }
    if (activeStep === "split") {
      return renderSplitWork();
    }
    if (activeStep === "input") {
      return renderInputWork();
    }
    return renderOutputWork();
  }

  function renderDevPreviewSwitcher(): ReactNode {
    if (!devPreviewEnabled) {
      return null;
    }
    return (
      <div className="dev-preview-switcher" aria-label="デベロッパーモード画面切替">
        <span>DEV</span>
        {steps.map((step, index) => (
          <button
            aria-pressed={activeStep === step.id}
            className={activeStep === step.id ? "active" : ""}
            key={step.id}
            onClick={() => switchDevPreviewStep(step.id)}
            type="button"
          >
            STEP{index + 1}
          </button>
        ))}
      </div>
    );
  }

  function openSearchTermModal(): void {
    setDraftSelectedSearchTerms(selectedSearchTermValues);
    setDraftCustomSearchTerms(customSearchTerms);
    setCustomSearchTermInput("");
    setSearchTermModalOpen(true);
  }

  function toggleDraftSearchTerm(term: string): void {
    setDraftSelectedSearchTerms((current) =>
      current.includes(term) ? current.filter((item) => item !== term) : [...current, term]
    );
  }

  function addDraftCustomSearchTerm(): void {
    const term = normalizeSearchTerm(customSearchTermInput);
    if (!term) {
      return;
    }
    setDraftCustomSearchTerms((current) => uniqueSearchTerms([...current, term]));
    setDraftSelectedSearchTerms((current) => uniqueSearchTerms([...current, term]));
    setCustomSearchTermInput("");
  }

  function removeDraftCustomSearchTerm(term: string): void {
    setDraftCustomSearchTerms((current) => current.filter((item) => item !== term));
    setDraftSelectedSearchTerms((current) => current.filter((item) => item !== term));
  }

  function applySearchTermPreset(): void {
    const preset: SearchTermPreset = {
      customTerms: uniqueSearchTerms(draftCustomSearchTerms),
      selectedTerms: uniqueSearchTerms(draftSelectedSearchTerms)
    };
    setCustomSearchTerms(preset.customTerms);
    setSelectedSearchTerms(selectedSearchTermsFromPreset(preset));
    saveSearchTermPreset(preset);
    setSearchTermModalOpen(false);
    setSearchResults([]);
    setSelectedSearchHit(null);
    setSearchHighlights([]);
    setStatus(preset.selectedTerms.length ? "検索用語を更新しました。" : "用語を選択してください。");
  }

  function renderHighlightedOcrText(): ReactNode {
    const text = pageText || "テキストなし";
    const terms = selectedSearchTermValues;
    if (!terms.length || !pageText) {
      return text;
    }
    const termsByLower = new Set(terms.map((term) => term.toLowerCase()));
    const escapedTerms = [...terms].sort((a, b) => b.length - a.length).map((term) => term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
    const parts = text.split(new RegExp(`(${escapedTerms.join("|")})`, "gi"));
    return parts.map((part, index) =>
      termsByLower.has(part.toLowerCase()) ? (
        <mark className="ocr-search-mark" key={`${part}-${index}`}>
          {part}
        </mark>
      ) : (
        <span key={`${part}-${index}`}>{part}</span>
      )
    );
  }

  function renderSearchEmptyState(): ReactNode {
    if (!selectedSearchTerms.length) {
      return <small className="muted-line">用語を選択してください。</small>;
    }
    return <small className="muted-line">検索結果なし</small>;
  }

  function renderSearchTermModal(): ReactNode {
    if (!searchTermModalOpen) {
      return null;
    }
    const draftAllTerms = uniqueSearchTerms([...CONTRACT_SEARCH_TERMS, ...draftCustomSearchTerms]);
    return (
      <div className="modal-backdrop" role="presentation">
        <section className="search-term-modal" aria-label="ハイライト対象用語" role="dialog" aria-modal="true">
          <div className="modal-header">
            <div>
              <h3>ハイライト対象用語</h3>
              <p>現在操作中PDFだけを検索します。</p>
            </div>
            <button aria-label="閉じる" className="icon-button" onClick={() => setSearchTermModalOpen(false)} type="button">
              <XCircle aria-hidden="true" size={18} />
            </button>
          </div>
          <div className="term-modal-section">
            <span className="group-label">契約書関連の選択肢</span>
            <div className="term-option-grid">
              {draftAllTerms.map((term) => (
                <button
                  aria-pressed={draftSelectedSearchTerms.includes(term)}
                  className={draftSelectedSearchTerms.includes(term) ? "term-option selected" : "term-option"}
                  key={term}
                  onClick={() => toggleDraftSearchTerm(term)}
                  type="button"
                >
                  {term}
                </button>
              ))}
            </div>
          </div>
          <div className="term-modal-section">
            <span className="group-label">任意の内容を追加</span>
            <div className="search-box">
              <input
                aria-label="追加する検索用語"
                onChange={(event) => setCustomSearchTermInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    addDraftCustomSearchTerm();
                  }
                }}
                value={customSearchTermInput}
              />
              <button disabled={!customSearchTermInput.trim()} onClick={addDraftCustomSearchTerm} type="button">
                追加
              </button>
            </div>
          </div>
          <div className="term-modal-section">
            <span className="group-label">追加済み用語</span>
            <div className="custom-term-list">
              {draftCustomSearchTerms.length ? (
                draftCustomSearchTerms.map((term) => (
                  <span className="term-search-chip removable" key={term}>
                    {term}
                    <button aria-label={`${term}を削除`} onClick={() => removeDraftCustomSearchTerm(term)} type="button">
                      <XCircle aria-hidden="true" size={14} />
                    </button>
                  </span>
                ))
              ) : (
                <small className="muted-line">追加済み用語なし</small>
              )}
            </div>
          </div>
          <div className="modal-actions">
            <button onClick={() => setSearchTermModalOpen(false)} type="button">
              キャンセル
            </button>
            <button className="primary" onClick={applySearchTermPreset} type="button">
              適用
            </button>
          </div>
        </section>
      </div>
    );
  }

  function renderRightPanel() {
    if (activeStep === "input") {
      return renderInputControls();
    }
    if (activeStep !== "split") {
      return null;
    }

    return (
      <aside className="right-panel legacy-split-right stack" aria-label="STEP2詳細操作">
        <PaneHeader title="分割設定" />
        <div className="legacy-panel-section current-page-section">
          <span className="group-label">現在ページ</span>
          <div className="current-page-detail">
            <StatLine label="ページ" value={currentFile ? `${currentPage} / ${currentFile.pageCount}` : "-"} />
            <StatLine label="範囲" value={currentVisibleSegment?.pages ?? "-"} />
            <StatLine label="分割点" value={currentSplitPoints.includes(currentPage) ? "あり" : "なし"} />
          </div>
          <div className="shortcut-strip">
            <button aria-keyshortcuts="Alt+ArrowLeft" disabled={!currentFile} onClick={() => void movePdf(-1)} type="button">
              前PDF
            </button>
            <button aria-keyshortcuts="Alt+ArrowRight" disabled={!currentFile} onClick={() => void movePdf(1)} type="button">
              次PDF
            </button>
          </div>
        </div>
        <div className="legacy-panel-section split-command-section">
          <span className="group-label">手動分割</span>
          <div className="action-row vertical">
            <button
              aria-keyshortcuts="Space Control+Enter"
              className="primary"
              disabled={!currentFile || currentPage <= 1}
              onClick={addSplitBeforeCurrentPage}
              title="現在ページの前で分割 (Space / Ctrl+Enter)"
              type="button"
            >
              <IconLabel icon={Split}>現在ページの前で分割</IconLabel>
            </button>
            <button
              aria-keyshortcuts="Control+Shift+U"
              disabled={!currentFile || currentPdfSplitPointCount === 0}
              onClick={undoLastSplit}
              title="最後の分割を取り消す (Ctrl+Shift+U)"
              type="button"
            >
              <IconLabel icon={Undo2}>最後の分割を取り消す</IconLabel>
            </button>
            <button
              aria-keyshortcuts="Delete"
              disabled={!currentFile || currentPdfSplitPointCount === 0}
              onClick={deleteSelectedSplitPoint}
              title="選択中の分割点を削除 (Delete)"
              type="button"
            >
              <IconLabel icon={Trash2}>選択分割を削除</IconLabel>
            </button>
          </div>
        </div>
        <div className="legacy-panel-section assist-section">
          <span className="group-label">検索</span>
          <div className="selected-search-terms" aria-label="選択中のハイライト用語">
            {selectedSearchTerms.length ? (
              selectedSearchTerms.map((item) => (
                <span className={item.source === "custom" ? "term-search-chip custom" : "term-search-chip"} key={item.term}>
                  {item.term}
                </span>
              ))
            ) : (
              <small className="muted-line">用語未選択</small>
            )}
          </div>
          <div className="search-command-row">
            <button onClick={openSearchTermModal} type="button">
              用語を選択
            </button>
            <button disabled={!currentPdf || !selectedSearchTerms.length} onClick={() => void runTextSearch()} type="button">
              検索/ハイライト
            </button>
          </div>
          <div className="search-results">
            {searchResults.length ? (
              searchResults.map((result, index) => (
                <button
                  className={
                    selectedSearchHit?.pdfPath === result.pdfPath &&
                    selectedSearchHit?.pageNo === result.pageNo &&
                    selectedSearchHit?.index === index
                      ? "search-result-row selected"
                      : "search-result-row"
                  }
                  key={`${result.pdfPath}-${result.pageNo}-${index}`}
                  onClick={() => void selectSearchResult(result, index)}
                  type="button"
                >
                  <span className="search-result-meta">
                    <strong>{result.pageNo}ページ</strong>
                    <small>{result.totalCount}件</small>
                    <small className="state-pill">{result.matchedTerms.join(" / ")}</small>
                    {result.pdfPath === currentPdf && result.pageNo === currentPage ? (
                      <small className="state-pill active">現在ページ</small>
                    ) : null}
                  </span>
                  <small>{result.snippets[0] || "スニペットなし"}</small>
                </button>
              ))
            ) : (
              renderSearchEmptyState()
            )}
          </div>
        </div>
        <div className="legacy-panel-section assist-section">
          <div className="section-title-row">
            <span className="group-label">候補検索</span>
            <button disabled={!currentPdf} onClick={() => void runIndexCandidateSearch()} type="button">
              候補取得
            </button>
          </div>
          <div className="index-candidates">
            {indexCandidates.length ? (
              indexCandidates.map((candidate, index) => (
                <button
                  className="index-candidate-row"
                  key={`${candidate.pdf_path}-${candidate.page_no}-${index}`}
                  onClick={() => void selectIndexCandidate(candidate)}
                  type="button"
                >
                  <span className="search-result-meta">
                    <strong>{candidate.page_no}ページ</strong>
                    <small>{Math.round(candidate.score * 100)}%</small>
                    <small className="state-pill">{candidate.reason}</small>
                  </span>
                  <small>{basename(candidate.pdf_path)}: {candidate.snippet}</small>
                </button>
              ))
            ) : (
              <small className="muted-line">候補なし</small>
            )}
          </div>
        </div>
        <div className="legacy-panel-section assist-section">
          <span className="group-label">白紙候補</span>
          <div className="blank-candidates">
            {blankCandidates.length ? (
              blankCandidates.map((candidate) => (
                <button
                  className="blank-candidate-row"
                  key={candidate.page_no}
                  onClick={() => void selectPageForPreview(currentPdf, candidate.page_no)}
                  type="button"
                >
                  <span>{candidate.page_no}ページ</span>
                  <strong>{Math.round(candidate.score * 100)}%</strong>
                </button>
              ))
            ) : (
              <small className="muted-line">候補なし</small>
            )}
          </div>
        </div>
        {renderOcrTextPanel()}
        <div className="legacy-panel-section completion-section">
          <span className="group-label">完了操作</span>
          <div className="split-footer split-settings-continue">
            <button className="primary wide" disabled={!allSegments.length} onClick={() => setActiveStep("input")} type="button">
              <IconLabel icon={ChevronRight}>入力へ進む</IconLabel>
            </button>
          </div>
        </div>
      </aside>
    );
  }

  return (
    <main className={activeStep === "split" || activeStep === "input" ? "app-shell split-screen-shell" : "app-shell"}>
      <header className="app-header">
        <div className="brand-row compact-brand">
          <span className="brand-mark">PDF</span>
          <div>
            <p className="section-label">PDF分割命名ツール</p>
            <h1>PDF整理ツール</h1>
          </div>
        </div>
        <div className="current-step-banner" aria-label="現在の作業ステップ">
          <span className="step-index">{activeStepIndex + 1}</span>
          <span>
            <strong>
              <ActiveStepIcon aria-hidden="true" size={16} strokeWidth={2.1} />
              {activeStepMeta.label}
            </strong>
            <small>{activeStepMeta.hint}</small>
          </span>
        </div>
        <section className={splitHeaderSummary ? "header-summary split-header-summary" : "header-summary"} aria-label="作業状況">
          {splitHeaderSummary ? (
            splitHeaderSummary.map((item) => <StatLine key={item.label} label={item.label} value={item.value} />)
          ) : (
            <>
              <StatLine label="PDF" value={`${pdfFiles.length}件`} />
              <StatLine label="分割" value={`${allSegments.length}件`} />
              <StatLine label="入力" value={allSegments.length ? `${readySegments}件 OK` : "未確認"} />
              <StatLine label="出力先" value={outputDir ? "設定済み" : "未設定"} />
            </>
          )}
        </section>
        <div className="header-actions">
          {renderDevPreviewSwitcher()}
          <div className={`update-card ${updateTone}`}>
            <div className="update-copy">
              <small>現在のバージョン: {currentVersion}</small>
              <strong>{updateMessage}</strong>
              {updateProgress ? <span>{updateProgress}</span> : null}
              {availableUpdate?.body ? (
                <details className="update-notes">
                  <summary>リリースメモ</summary>
                  <p>{availableUpdate.body}</p>
                </details>
              ) : null}
            </div>
            <div className="update-actions">
              <button disabled={updateState === "checking" || updateState === "installing"} onClick={() => void checkForUpdates(true)} type="button">
                <IconLabel icon={RefreshCw}>更新確認</IconLabel>
              </button>
              {availableUpdate ? (
                <button className="primary" disabled={updateState === "installing"} onClick={() => void installAvailableUpdate()} type="button">
                  <IconLabel icon={Download}>インストール</IconLabel>
                </button>
              ) : null}
            </div>
          </div>
          <div className={`status-pill ${statusTone}`} role="status">
            {statusTone === "danger" ? (
              <AlertTriangle aria-hidden="true" size={16} />
            ) : statusTone === "ok" ? (
              <CheckCircle2 aria-hidden="true" size={16} />
            ) : (
              <ClipboardCheck aria-hidden="true" size={16} />
            )}
            <span>{status}</span>
          </div>
        </div>
      </header>

      <nav className="stepper" aria-label="作業ステップ">
        {steps.map((step, index) => {
          const state = stepState(step.id);
          const Icon = step.icon;
          return (
            <button
              aria-current={activeStep === step.id ? "step" : undefined}
              className={`step-tab ${state}`}
              data-testid={`step-${step.id}`}
              key={step.id}
              onClick={() => (devPreviewEnabled ? switchDevPreviewStep(step.id) : setActiveStep(step.id))}
              type="button"
            >
              <span className="step-index">{index + 1}</span>
              <span className="step-copy">
                <strong>
                  <Icon aria-hidden="true" size={16} strokeWidth={2.1} />
                  {step.label}
                </strong>
              </span>
              <span className={`step-badge ${state}`}>{stepStateLabel(state)}</span>
            </button>
          );
        })}
      </nav>

      <section
        className={
          activeStep === "import"
            ? "task-layout import-single-layout"
            : activeStep === "input"
              ? "task-layout split-focused-layout input-focused-layout"
              : activeStep === "split"
                ? "task-layout split-focused-layout"
                : "task-layout"
        }
        aria-label="PDF整理ワークスペース"
      >
        {renderLeftPane()}
        {renderWorkPane()}
        {renderRightPanel()}
      </section>
      {renderSearchTermModal()}
    </main>
  );
}

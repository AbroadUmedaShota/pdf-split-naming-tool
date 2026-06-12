"use client";

import { confirm, open } from "@tauri-apps/plugin-dialog";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  ChevronRight,
  ClipboardCheck,
  Download,
  FileText,
  FolderOpen,
  ListChecks,
  PencilLine,
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
  type SidecarExportResponse,
  type SidecarOutputCheck,
  type SidecarPdfInfoResponse,
  type SidecarPreviewResponse,
  type SidecarResponse,
  type SidecarSegment
} from "../lib/sidecar";
import {
  checkForAppUpdate,
  installAppUpdate,
  readCurrentVersion,
  updateErrorMessage,
  type AppUpdate
} from "../lib/updates";

type StepId = "import" | "split" | "input" | "output";

type PdfFile = {
  path: string;
  pageCount: number;
};

type SegmentView = {
  key: string;
  pdfPath: string;
  startPage: number;
  endPage: number;
  pages: string;
  metadata: Record<string, string>;
};

type StepState = "active" | "done" | "attention" | "idle";
type UpdateState = "idle" | "checking" | "current" | "available" | "installing" | "installed" | "error";
type StatusTone = "ok" | "warning" | "danger" | "";
type BusyAction = "" | "import" | "remove" | "preflight" | "export" | "save" | "load";

const steps: Array<{ id: StepId; label: string; hint: string; icon: LucideIcon }> = [
  { id: "import", label: "PDF取込", hint: "PDF / 出力先", icon: FileText },
  { id: "split", label: "分割", hint: "ページ範囲", icon: Split },
  { id: "input", label: "入力", hint: "箱No / 連番", icon: PencilLine },
  { id: "output", label: "出力", hint: "チェック / 実行", icon: Download }
];

const emptyCommonMetadata = { box_no: "", binder_no: "" };
const requiredMetadata = ["box_no", "binder_no", "seq"] as const;
const invalidFilenameChars = /[<>:"/\\|?*]/g;
const previewCacheLimit = 20;

function basename(path: string): string {
  return path.split(/[\\/]/).filter(Boolean).pop() ?? path;
}

function segmentKey(pdfPath: string, startPage: number, endPage: number): string {
  return `${pdfPath}#${startPage}-${endPage}`;
}

function pageLabel(startPage: number, endPage: number): string {
  return startPage === endPage ? `${startPage}` : `${startPage}-${endPage}`;
}

function previewCacheKey(pdfPath: string, pageNo: number): string {
  return `${pdfPath}#${pageNo}`;
}

function hasMetadataValues(metadata: Record<string, string>): boolean {
  return Object.values(metadata).some((value) => value.trim());
}

function segmentKeySetFor(file: PdfFile, splitPoints: number[]): Set<string> {
  const points = splitPointsFor(file.pageCount, splitPoints);
  const starts = [1, ...points];
  const ends = [...points.map((point) => point - 1), file.pageCount];
  return new Set(starts.map((startPage, index) => segmentKey(file.path, startPage, ends[index])));
}

function padMetadata(value: string, length: number): string {
  const trimmed = value.trim();
  return trimmed.length >= length ? trimmed : trimmed.padStart(length, "0");
}

function sanitizeFilename(filename: string): string {
  const sanitized = filename.replace(invalidFilenameChars, "_").trim().replace(/[. ]+$/g, "").replace(/\s+/g, " ");
  return sanitized || "output.pdf";
}

function previewFilename(metadata: Record<string, string>): string | null {
  if (missingMetadata(metadata).length) {
    return null;
  }
  return sanitizeFilename(
    `${padMetadata(metadata.box_no ?? "", 2)}_${padMetadata(metadata.binder_no ?? "", 2)}_${padMetadata(
      metadata.seq ?? "",
      3
    )}.pdf`
  );
}

function missingMetadata(metadata: Record<string, string>): string[] {
  return requiredMetadata.filter((key) => !String(metadata[key] ?? "").trim());
}

function sidecarError(response: SidecarResponse): string {
  return "error" in response ? response.error : "Sidecar response is not usable for this operation.";
}

function splitPointsFor(pageCount: number, splitPoints: number[] | undefined): number[] {
  return [...new Set(splitPoints ?? [])]
    .filter((page) => page > 1 && page <= pageCount)
    .sort((a, b) => a - b);
}

function buildSegments(
  pdfFiles: PdfFile[],
  splitPointsByPdf: Record<string, number[]>,
  segmentMetadata: Record<string, Record<string, string>>,
  commonMetadata: Record<string, string>
): SegmentView[] {
  return pdfFiles.flatMap((file) => {
    const points = splitPointsFor(file.pageCount, splitPointsByPdf[file.path]);
    const starts = [1, ...points];
    const ends = [...points.map((point) => point - 1), file.pageCount];
    return starts.map((startPage, index) => {
      const endPage = ends[index];
      const key = segmentKey(file.path, startPage, endPage);
      // 個別値が空欄の box_no / binder_no は除去し、共通値へフォールバックさせる（seq に共通値はない）
      const overrides = { ...(segmentMetadata[key] ?? {}) };
      if (!(overrides.box_no ?? "").trim()) {
        delete overrides.box_no;
      }
      if (!(overrides.binder_no ?? "").trim()) {
        delete overrides.binder_no;
      }
      return {
        key,
        pdfPath: file.path,
        startPage,
        endPage,
        pages: pageLabel(startPage, endPage),
        metadata: {
          box_no: commonMetadata.box_no ?? "",
          binder_no: commonMetadata.binder_no ?? "",
          seq: "",
          ...overrides
        }
      };
    });
  });
}

function toSidecarSegments(segments: SegmentView[]): SidecarSegment[] {
  return segments.map((segment) => ({
    pdf_path: segment.pdfPath,
    start_page: segment.startPage,
    end_page: segment.endPage,
    metadata: segment.metadata
  }));
}

function duplicateRequestedFilenames(checks: SidecarOutputCheck[]): Set<string> {
  const counts = new Map<string, number>();
  for (const check of checks) {
    if (check.requested_filename) {
      counts.set(check.requested_filename, (counts.get(check.requested_filename) ?? 0) + 1);
    }
  }
  return new Set([...counts.entries()].filter(([, count]) => count > 1).map(([name]) => name));
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

function StatLine({ label, tone, value }: { label: string; tone?: "warning"; value: string }) {
  return (
    <div className={tone === "warning" ? "stat-line warning" : "stat-line"}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

export default function Page() {
  const [activeStep, setActiveStep] = useState<StepId>("import");
  const [pdfFiles, setPdfFiles] = useState<PdfFile[]>([]);
  const [currentPdf, setCurrentPdf] = useState("");
  const [currentPage, setCurrentPage] = useState(1);
  const [previewDataUrl, setPreviewDataUrl] = useState("");
  const [outputDir, setOutputDir] = useState("");
  const [commonMetadata, setCommonMetadata] = useState<Record<string, string>>(emptyCommonMetadata);
  const [splitPointsByPdf, setSplitPointsByPdf] = useState<Record<string, number[]>>({});
  const [segmentMetadata, setSegmentMetadata] = useState<Record<string, Record<string, string>>>({});
  const [selectedSegmentKey, setSelectedSegmentKey] = useState("");
  const [splitVisited, setSplitVisited] = useState(false);
  const [preflightChecks, setPreflightChecks] = useState<SidecarOutputCheck[]>([]);
  const [exportResult, setExportResult] = useState<SidecarExportResponse | null>(null);
  const [status, setStatusState] = useState<{ message: string; tone: StatusTone }>({
    message: "PDFを選択してください。",
    tone: ""
  });
  const [busy, setBusy] = useState<BusyAction>("");
  const [previewLoading, setPreviewLoading] = useState(false);
  const previewGenerationRef = useRef(0);
  const previewCacheRef = useRef<Map<string, string>>(new Map());
  const pageRequestRef = useRef(1); // 楽観更新用の要求中ページ。currentPage は描画用
  const [currentVersion, setCurrentVersion] = useState("0.1.0");
  const [updateState, setUpdateState] = useState<UpdateState>("idle");
  const [updateMessage, setUpdateMessage] = useState("更新未確認");
  const [updateProgress, setUpdateProgress] = useState("");
  const [availableUpdate, setAvailableUpdate] = useState<AppUpdate | null>(null);

  const currentFile = pdfFiles.find((file) => file.path === currentPdf);
  const allSegments = useMemo(
    () => buildSegments(pdfFiles, splitPointsByPdf, segmentMetadata, commonMetadata),
    [pdfFiles, splitPointsByPdf, segmentMetadata, commonMetadata]
  );
  const selectedSegment = allSegments.find((segment) => segment.key === selectedSegmentKey) ?? allSegments[0];
  const totalPages = useMemo(() => pdfFiles.reduce((total, file) => total + file.pageCount, 0), [pdfFiles]);
  const incompleteSegments = useMemo(
    () => allSegments.filter((segment) => missingMetadata(segment.metadata).length > 0).length,
    [allSegments]
  );
  const readySegments = Math.max(0, allSegments.length - incompleteSegments);
  const outputIssues = preflightChecks.filter((check) => !check.ok).length;
  const existingOutputs = preflightChecks.filter((check) => check.has_existing_output).length;
  const canContinueFromImport = pdfFiles.length > 0 && Boolean(outputDir);
  const canRunPreflight = allSegments.length > 0 && Boolean(outputDir);
  const canExport = preflightChecks.length > 0 && outputIssues === 0;
  const isBusy = busy !== "";
  // 応答待ち中に編集された場合の検出用。送信内容のシグネチャと出力先の最新値を ref に写す
  const requestSignature = useMemo(() => JSON.stringify(toSidecarSegments(allSegments)), [allSegments]);
  const requestSignatureRef = useRef(requestSignature);
  requestSignatureRef.current = requestSignature;
  const outputDirRef = useRef(outputDir);
  outputDirRef.current = outputDir;
  // 直近で成功した preflight の送信内容。出力実行前の同一性チェックに使う
  const preflightSnapshotRef = useRef<{ signature: string; outputDir: string } | null>(null);
  const duplicateRequestedNames = useMemo(() => duplicateRequestedFilenames(preflightChecks), [preflightChecks]);
  const outputShortages: Array<{ step: StepId; stepLabel: string; label: string }> = [];
  if (!pdfFiles.length) {
    outputShortages.push({ step: "import", stepLabel: "PDF取込", label: "PDFが未選択" });
  }
  if (!outputDir) {
    outputShortages.push({ step: "import", stepLabel: "PDF取込", label: "出力先が未設定" });
  }
  if (pdfFiles.length > 0 && incompleteSegments > 0) {
    outputShortages.push({ step: "input", stepLabel: "入力", label: `未入力${incompleteSegments}件` });
  }

  function setStatus(message: string, tone: StatusTone = ""): void {
    setStatusState({ message, tone });
  }

  function busyLabel(action: BusyAction, label: string): string {
    return busy === action ? "処理中…" : label;
  }

  function clearOutputState(): void {
    preflightSnapshotRef.current = null;
    setPreflightChecks([]);
    setExportResult(null);
  }

  function readPreviewCache(key: string): string | undefined {
    const cache = previewCacheRef.current;
    const value = cache.get(key);
    if (value !== undefined) {
      cache.delete(key);
      cache.set(key, value);
    }
    return value;
  }

  function writePreviewCache(key: string, value: string): void {
    const cache = previewCacheRef.current;
    cache.delete(key);
    cache.set(key, value);
    while (cache.size > previewCacheLimit) {
      const oldest = cache.keys().next().value;
      if (oldest === undefined) {
        break;
      }
      cache.delete(oldest);
    }
  }

  function dropPreviewCacheFor(pdfPath: string): void {
    const cache = previewCacheRef.current;
    for (const key of [...cache.keys()]) {
      if (key.startsWith(`${pdfPath}#`)) {
        cache.delete(key);
      }
    }
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
    if (activeStep === "split") {
      setSplitVisited(true);
    }
  }, [activeStep]);

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
        setStatus("最新版です。", "ok");
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
        setStatus(`更新確認エラー: ${message}`, "danger");
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
      setStatus("更新をインストールしました。", "ok");
    } catch (error) {
      const message = updateErrorMessage(error);
      setUpdateState("error");
      setUpdateMessage(`更新インストールに失敗しました: ${message}`);
      setStatus(`更新インストールエラー: ${message}`, "danger");
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
      if (!allSegments.length) {
        return "idle";
      }
      const hasSplitPoints = pdfFiles.some(
        (file) => splitPointsFor(file.pageCount, splitPointsByPdf[file.path]).length > 0
      );
      return hasSplitPoints || splitVisited ? "done" : "idle";
    }
    if (stepId === "input") {
      if (!allSegments.length) {
        return "idle";
      }
      return incompleteSegments ? "attention" : "done";
    }
    if (stepId === "output") {
      if (exportResult) {
        if (exportResult.summary.failed > 0) {
          return "attention";
        }
        if (exportResult.summary.created > 0) {
          return "done";
        }
      }
      if (outputIssues) {
        return "attention";
      }
      return "idle";
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

  async function loadPreview(pdfPath: string, pageNo: number): Promise<void> {
    const generation = ++previewGenerationRef.current;
    const cached = readPreviewCache(previewCacheKey(pdfPath, pageNo));
    if (cached !== undefined) {
      setPreviewDataUrl(cached);
      setPreviewLoading(false);
      return;
    }
    setPreviewLoading(true);
    try {
      const response = await invokeSidecar({ command: "page_preview", pdf_path: pdfPath, page_no: pageNo });
      if (!response.ok || response.command !== "page_preview") {
        throw new Error(response.ok ? "プレビューを取得できませんでした。" : sidecarError(response));
      }
      const preview = response as SidecarPreviewResponse;
      // キャッシュキーは要求側パスに統一する（応答側パスは区切り文字が異なりうる）
      writePreviewCache(previewCacheKey(pdfPath, pageNo), preview.image_data_url);
      if (generation !== previewGenerationRef.current) {
        return;
      }
      setPreviewDataUrl(preview.image_data_url);
      setPreviewLoading(false);
    } catch (error) {
      if (generation === previewGenerationRef.current) {
        setPreviewLoading(false);
        throw error;
      }
    }
  }

  async function choosePdfs(): Promise<void> {
    if (busy) {
      return;
    }
    setBusy("import");
    try {
      const selected = await open({
        multiple: true,
        filters: [{ name: "PDF", extensions: ["pdf"] }]
      });
      const paths = Array.isArray(selected) ? selected : selected ? [selected] : [];
      if (!paths.length) {
        return;
      }
      const loaded = await Promise.all(paths.map((path) => loadPdfInfo(path)));
      for (const file of loaded) {
        dropPreviewCacheFor(file.path);
      }
      setPdfFiles((existing) => {
        const byPath = new Map(existing.map((file) => [file.path, file]));
        for (const file of loaded) {
          byPath.set(file.path, file);
        }
        return [...byPath.values()];
      });
      setCurrentPdf(loaded[0].path);
      pageRequestRef.current = 1;
      setCurrentPage(1);
      setSplitVisited(false);
      clearOutputState();
      await loadPreview(loaded[0].path, 1);
      setStatus(`${loaded.length}件のPDFを読み込みました。`, "ok");
    } catch (error) {
      setStatus(`PDF取込エラー: ${String(error)}`, "danger");
    } finally {
      setBusy("");
    }
  }

  async function chooseOutputDir(): Promise<void> {
    if (busy) {
      return;
    }
    const selected = await open({ directory: true, multiple: false });
    if (typeof selected === "string") {
      setOutputDir(selected);
      clearOutputState();
      setStatus("出力フォルダを設定しました。", "ok");
    }
  }

  async function selectPdf(path: string): Promise<void> {
    if (busy) {
      return;
    }
    setCurrentPdf(path);
    pageRequestRef.current = 1;
    setCurrentPage(1);
    try {
      await loadPreview(path, 1);
    } catch (error) {
      setStatus(`プレビューエラー: ${String(error)}`, "danger");
    }
  }

  async function removePdf(path: string): Promise<void> {
    if (busy) {
      return;
    }
    const hasInputs =
      Object.entries(segmentMetadata).some(
        ([key, metadata]) => key.startsWith(`${path}#`) && hasMetadataValues(metadata)
      ) || (splitPointsByPdf[path] ?? []).length > 0;
    if (hasInputs) {
      const proceed = await confirm(
        `${basename(path)} の入力済みの値と分割点が失われます。一覧から外しますか？`,
        { title: "PDFの除外", kind: "warning" }
      );
      if (!proceed) {
        return;
      }
    }
    setBusy("remove");
    try {
      dropPreviewCacheFor(path);
      const remaining = pdfFiles.filter((file) => file.path !== path);
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
        pageRequestRef.current = 1;
        setCurrentPage(1);
        setPreviewDataUrl("");
        if (nextPdf) {
          try {
            await loadPreview(nextPdf.path, 1);
          } catch (error) {
            setStatus(`プレビューエラー: ${String(error)}`, "danger");
            return;
          }
        }
      }
      setStatus(`${basename(path)} を一覧から外しました。`, "ok");
    } finally {
      setBusy("");
    }
  }

  async function clearPdfSelection(): Promise<void> {
    if (busy) {
      return;
    }
    const hasInputs =
      Object.values(segmentMetadata).some((metadata) => hasMetadataValues(metadata)) ||
      Object.values(splitPointsByPdf).some((points) => points.length > 0);
    if (hasInputs) {
      const proceed = await confirm("入力済みの値と分割点が失われます。PDF一覧をクリアしますか？", {
        title: "全クリア",
        kind: "warning"
      });
      if (!proceed) {
        return;
      }
    }
    previewCacheRef.current.clear();
    setPdfFiles([]);
    setCurrentPdf("");
    pageRequestRef.current = 1;
    setCurrentPage(1);
    setPreviewDataUrl("");
    setSplitPointsByPdf({});
    setSegmentMetadata({});
    setSelectedSegmentKey("");
    setSplitVisited(false);
    clearOutputState();
    setStatus("PDF一覧をクリアしました。", "ok");
  }

  function resetOutputDir(): void {
    if (busy) {
      return;
    }
    setOutputDir("");
    clearOutputState();
    setStatus("出力先をリセットしました。", "ok");
  }

  async function movePage(offset: number): Promise<void> {
    if (!currentFile || busy) {
      return;
    }
    const nextPage = Math.max(1, Math.min(currentFile.pageCount, pageRequestRef.current + offset));
    if (nextPage === pageRequestRef.current) {
      return;
    }
    pageRequestRef.current = nextPage;
    setCurrentPage(nextPage);
    try {
      await loadPreview(currentFile.path, nextPage);
    } catch (error) {
      setStatus(`ページ移動エラー: ${String(error)}`, "danger");
    }
  }

  async function applySplitPoints(file: PdfFile, nextPoints: number[], message: string): Promise<void> {
    const nextKeys = segmentKeySetFor(file, nextPoints);
    const orphanKeys = Object.keys(segmentMetadata).filter(
      (key) => key.startsWith(`${file.path}#`) && !nextKeys.has(key)
    );
    const filledCount = orphanKeys.filter((key) => hasMetadataValues(segmentMetadata[key] ?? {})).length;
    if (filledCount > 0) {
      const proceed = await confirm(`入力済み${filledCount}件の値が失われます。続行しますか？`, {
        title: "分割の変更",
        kind: "warning"
      });
      if (!proceed) {
        return;
      }
    }
    clearOutputState();
    setSplitPointsByPdf((current) => ({
      ...current,
      [file.path]: splitPointsFor(file.pageCount, nextPoints)
    }));
    if (orphanKeys.length) {
      setSegmentMetadata((current) => {
        const next = { ...current };
        for (const key of orphanKeys) {
          delete next[key];
        }
        return next;
      });
    }
    setStatus(message, "ok");
  }

  async function addSplitBeforeCurrentPage(): Promise<void> {
    if (!currentFile || currentPage <= 1) {
      setStatus("先頭ページの前では分割できません。", "warning");
      return;
    }
    await applySplitPoints(
      currentFile,
      [...(splitPointsByPdf[currentFile.path] ?? []), currentPage],
      `${currentPage}ページの前に分割を追加しました。`
    );
  }

  async function undoLastSplit(): Promise<void> {
    if (!currentFile) {
      return;
    }
    const points = splitPointsFor(currentFile.pageCount, splitPointsByPdf[currentFile.path]);
    await applySplitPoints(currentFile, points.slice(0, -1), "最後の分割を取り消しました。");
  }

  async function splitEveryPage(): Promise<void> {
    if (!currentFile) {
      return;
    }
    await applySplitPoints(
      currentFile,
      Array.from({ length: Math.max(0, currentFile.pageCount - 1) }, (_value, index) => index + 2),
      "1ページごとの分割にしました。"
    );
  }

  function updateCommonMetadata(key: "box_no" | "binder_no", value: string): void {
    clearOutputState();
    setCommonMetadata((current) => ({ ...current, [key]: value }));
  }

  function updateMetadata(segment: SegmentView, key: string, value: string): void {
    clearOutputState();
    setSegmentMetadata((current) => ({
      ...current,
      [segment.key]: {
        ...(current[segment.key] ?? {}),
        [key]: value
      }
    }));
  }

  async function resequence(): Promise<void> {
    if (busy) {
      return;
    }
    const overwriteCount = allSegments.filter((segment) => segment.metadata.seq.trim()).length;
    if (overwriteCount > 0) {
      const proceed = await confirm(`${overwriteCount}件の連番を上書きします。続行しますか？`, {
        title: "連番の再採番",
        kind: "warning"
      });
      if (!proceed) {
        return;
      }
    }
    clearOutputState();
    setSegmentMetadata((current) => {
      const next = { ...current };
      allSegments.forEach((segment, index) => {
        next[segment.key] = { ...(next[segment.key] ?? {}), seq: String(index + 1) };
      });
      return next;
    });
    setStatus("連番を再採番しました。", "ok");
  }

  async function runPreflight(): Promise<void> {
    if (busy) {
      return;
    }
    setBusy("preflight");
    try {
      const segments = toSidecarSegments(allSegments);
      const sentSignature = JSON.stringify(segments);
      const sentOutputDir = outputDir;
      const response = await invokeSidecar({ command: "preflight", output_dir: sentOutputDir, segments });
      if (!response.ok || !("checks" in response)) {
        throw new Error(sidecarError(response));
      }
      // 応答待ち中にセグメントや出力先が編集された場合、古いチェック結果は適用しない
      if (sentSignature !== requestSignatureRef.current || sentOutputDir !== outputDirRef.current) {
        setStatus("内容が変更されたため再チェックしてください。", "warning");
        return;
      }
      preflightSnapshotRef.current = { signature: sentSignature, outputDir: sentOutputDir };
      setPreflightChecks(response.checks);
      setExportResult(null);
      const duplicates = duplicateRequestedFilenames(response.checks);
      if (!response.can_run) {
        setStatus("修正が必要な項目があります。", "warning");
      } else if (duplicates.size) {
        setStatus("出力できますが、同じ予定ファイル名が複数あります。連番を確認してください。", "warning");
      } else {
        setStatus("出力できます。", "ok");
      }
      setActiveStep("output");
    } catch (error) {
      setStatus(`出力前チェックエラー: ${String(error)}`, "danger");
    } finally {
      setBusy("");
    }
  }

  async function runExport(): Promise<void> {
    if (busy) {
      return;
    }
    const segments = toSidecarSegments(allSegments);
    const snapshot = preflightSnapshotRef.current;
    // チェック済み内容と現在の内容が一致しない限り出力しない
    if (!snapshot || snapshot.signature !== JSON.stringify(segments) || snapshot.outputDir !== outputDir) {
      clearOutputState();
      setStatus("内容が変更されたため再チェックしてください。", "warning");
      return;
    }
    setBusy("export");
    try {
      const response = await invokeSidecar({ command: "export", output_dir: outputDir, segments });
      if (!("summary" in response) || !("items" in response)) {
        throw new Error(sidecarError(response));
      }
      preflightSnapshotRef.current = null;
      setExportResult(response);
      setPreflightChecks([]);
      if (response.ok && response.summary.failed === 0) {
        setStatus("出力が完了しました。", "ok");
      } else {
        setStatus(`出力結果を確認してください。失敗 ${response.summary.failed}件`, "warning");
      }
    } catch (error) {
      setStatus(`出力エラー: ${String(error)}`, "danger");
    } finally {
      setBusy("");
    }
  }

  async function saveState(): Promise<void> {
    if (busy) {
      return;
    }
    setBusy("save");
    try {
      const currentKeys = new Set(allSegments.map((segment) => segment.key));
      const filteredSegmentMetadata = Object.fromEntries(
        Object.entries(segmentMetadata).filter(([key]) => currentKeys.has(key))
      );
      // segment_metadata と同様に、現在の PDF 一覧に存在しないパスの分割点は保存しない
      const currentPdfPaths = new Set(pdfFiles.map((file) => file.path));
      const filteredSplitPoints = Object.fromEntries(
        Object.entries(splitPointsByPdf).filter(([path]) => currentPdfPaths.has(path))
      );
      const state: AppPersistedState = {
        version: 1,
        input_paths: pdfFiles.map((file) => file.path),
        output_dir: outputDir,
        split_points_by_pdf: filteredSplitPoints,
        segment_metadata: filteredSegmentMetadata,
        common_metadata: commonMetadata,
        current_pdf: currentPdf,
        current_page: currentPage,
        active_step: activeStep
      };
      const response = await invokeSidecar({ command: "state_save", state });
      if (!response.ok) {
        setStatus(`状態保存エラー: ${sidecarError(response)}`, "danger");
        return;
      }
      setStatus("状態を保存しました。", "ok");
    } catch (error) {
      setStatus(`状態保存エラー: ${String(error)}`, "danger");
    } finally {
      setBusy("");
    }
  }

  async function loadState(): Promise<void> {
    if (busy) {
      return;
    }
    const hasWork =
      pdfFiles.length > 0 ||
      hasMetadataValues(commonMetadata) ||
      Object.values(segmentMetadata).some((metadata) => hasMetadataValues(metadata));
    if (hasWork) {
      const proceed = await confirm("現在の作業内容を破棄して保存済み状態を復元しますか？", {
        title: "状態の復元",
        kind: "warning"
      });
      if (!proceed) {
        return;
      }
    }
    setBusy("load");
    try {
      const response = await invokeSidecar({ command: "state_load" });
      if (!response.ok || response.command !== "state_load") {
        setStatus(response.ok ? "状態読込エラー: 状態読込に失敗しました。" : `状態読込エラー: ${sidecarError(response)}`, "danger");
        return;
      }
      const state = response.state as Partial<AppPersistedState>;
      const inputPaths = Array.isArray(state.input_paths) ? state.input_paths : [];
      if (!inputPaths.length) {
        setStatus("保存済み状態はありません。");
        return;
      }
      const results = await Promise.allSettled(inputPaths.map((path) => loadPdfInfo(path)));
      const loaded: PdfFile[] = [];
      const missingNames: string[] = [];
      results.forEach((result, index) => {
        if (result.status === "fulfilled") {
          loaded.push(result.value);
        } else {
          missingNames.push(basename(inputPaths[index]));
        }
      });
      if (!loaded.length) {
        setStatus(`状態読込エラー: PDFを読み込めませんでした: ${missingNames.join(", ")}`, "danger");
        return;
      }
      previewCacheRef.current.clear();
      setPdfFiles(loaded);
      setOutputDir(state.output_dir ?? "");
      setSplitPointsByPdf(state.split_points_by_pdf ?? {});
      setSegmentMetadata(state.segment_metadata ?? {});
      setCommonMetadata({ ...emptyCommonMetadata, ...(state.common_metadata ?? {}) });
      const targetPdf = loaded.find((file) => file.path === state.current_pdf) ?? loaded[0];
      const targetPage = Math.max(1, Math.min(targetPdf.pageCount, state.current_page ?? 1));
      setCurrentPdf(targetPdf.path);
      pageRequestRef.current = targetPage;
      setCurrentPage(targetPage);
      setSelectedSegmentKey("");
      clearOutputState();
      const restoredStep = steps.some((step) => step.id === state.active_step)
        ? (state.active_step as StepId)
        : "import";
      setActiveStep(restoredStep);
      setSplitVisited(restoredStep !== "import");
      if (missingNames.length) {
        setStatus(
          `${inputPaths.length}件中${missingNames.length}件は読み込めませんでした: ${missingNames.join(
            ", "
          )}。このまま保存すると読み込めなかったPDFの入力値は失われます。`,
          "warning"
        );
      } else {
        setStatus("状態を復元しました。", "ok");
      }
      try {
        await loadPreview(targetPdf.path, targetPage);
      } catch (previewError) {
        setStatus(`プレビューエラー: ${String(previewError)}`, "danger");
      }
    } catch (error) {
      setStatus(`状態読込エラー: ${String(error)}`, "danger");
    } finally {
      setBusy("");
    }
  }

  const updateTone =
    updateState === "error"
      ? "danger"
      : updateState === "available" || updateState === "installing"
        ? "warning"
        : updateState === "current" || updateState === "installed"
          ? "ok"
          : "";

  function renderImportList() {
    return (
      <div className="pane stack">
        <PaneHeader
          title="PDF一覧"
          description={pdfFiles.length ? `${pdfFiles.length}件 / ${totalPages}ページ` : "処理対象PDFを追加します。"}
          action={
            <button
              className="ghost danger"
              disabled={!pdfFiles.length || isBusy}
              onClick={() => void clearPdfSelection()}
              type="button"
            >
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
                  disabled={isBusy}
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
              <button className="primary" disabled={isBusy} onClick={choosePdfs} type="button">
                <IconLabel icon={Upload}>{busyLabel("import", "PDFを選択")}</IconLabel>
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
      <div className="pane stack">
        <PaneHeader
          title="分割対象"
          description={currentFile ? `${basename(currentFile.path)} / ${currentPage}ページ目` : "PDF未選択"}
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
          <span className="group-label">セグメント</span>
          <div className="queue-list slim">
            {allSegments.length ? (
              allSegments.map((segment) => {
                const filename = previewFilename(segment.metadata);
                return (
                  <button
                    className={segment.key === selectedSegment?.key ? "list-row selected" : "list-row"}
                    key={segment.key}
                    onClick={() => setSelectedSegmentKey(segment.key)}
                    type="button"
                  >
                    <span>
                      <strong>{segment.pages}ページ</strong>
                      <small>{basename(segment.pdfPath)}</small>
                    </span>
                    <span className={filename ? "row-meta" : "row-meta warning"}>{filename ?? "未入力"}</span>
                  </button>
                );
              })
            ) : (
              <EmptyState icon={Split} title="分割なし">
                PDFを選択するとページ範囲が表示されます。
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
        <PaneHeader title="セグメント一覧" description={`${readySegments}件 OK / ${incompleteSegments}件 未入力`} />
        {allSegments.length ? (
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
                  onClick={() => setSelectedSegmentKey(segment.key)}
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
        ) : (
          <EmptyState icon={PencilLine} title="入力対象がありません">
            PDFを取込み、分割を確認してから入力します。
          </EmptyState>
        )}
      </div>
    );
  }

  function renderShortageActions() {
    const stepsToVisit = [...new Map(outputShortages.map((item) => [item.step, item])).values()];
    if (!stepsToVisit.length) {
      return null;
    }
    return (
      <div className="action-row">
        {stepsToVisit.map((item) => (
          <button key={item.step} onClick={() => setActiveStep(item.step)} type="button">
            <IconLabel icon={ArrowLeft}>{`${item.stepLabel}へ戻る`}</IconLabel>
          </button>
        ))}
      </div>
    );
  }

  function shortageSummary(): string {
    return `不足している項目: ${outputShortages.map((item) => item.label).join(" / ")}。下のボタンから該当ステップへ戻れます。`;
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
            {preflightChecks.map((check, index) => {
              const renamed =
                check.has_existing_output && Boolean(check.filename) && check.filename !== check.requested_filename;
              const duplicate = Boolean(check.requested_filename) && duplicateRequestedNames.has(check.requested_filename);
              return (
                <div
                  className={!check.ok ? "output-row error" : duplicate ? "output-row warning" : "output-row"}
                  key={`${check.pdf_path}-${check.pages}-${index}`}
                >
                  <span>
                    <strong>{check.requested_filename || check.filename || "-"}</strong>
                    <small>{check.pages}ページ</small>
                    {renamed ? (
                      <small className="rename-note">{`→ ${check.filename} として保存（上書きしません）`}</small>
                    ) : null}
                  </span>
                  <span className={check.ok && !duplicate ? "state-text ok" : "state-text warning"}>
                    {!check.ok ? "要修正" : duplicate ? "連番重複" : check.has_existing_output ? "既存あり" : "出力可能"}
                  </span>
                </div>
              );
            })}
          </div>
        ) : (
          <EmptyState
            action={
              outputShortages.length ? (
                renderShortageActions()
              ) : (
                <button disabled={!canRunPreflight || isBusy} onClick={runPreflight} type="button">
                  <IconLabel icon={ClipboardCheck}>{busyLabel("preflight", "出力前チェック")}</IconLabel>
                </button>
              )
            }
            icon={Download}
            title="未確認です"
          >
            {outputShortages.length ? shortageSummary() : "入力内容が揃ったら、ここで出力可否を確認します。"}
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
      <section className="work-card stack" aria-label="PDF取込">
        <PaneHeader title="取込設定" description="対象PDF、出力先、共通項目をここで揃えます。" />
        <div className="action-row">
          <button className="primary" disabled={isBusy} onClick={choosePdfs} type="button">
            <IconLabel icon={Upload}>{busyLabel("import", "PDFを選択")}</IconLabel>
          </button>
          <button disabled={isBusy} onClick={chooseOutputDir} type="button">
            <IconLabel icon={FolderOpen}>出力フォルダ</IconLabel>
          </button>
          <button disabled={!outputDir || isBusy} onClick={resetOutputDir} type="button">
            <IconLabel icon={XCircle}>出力先リセット</IconLabel>
          </button>
        </div>
        <div className="field-grid two">
          <label>
            箱No
            <input
              inputMode="numeric"
              name="box_no"
              value={commonMetadata.box_no}
              onChange={(event) => updateCommonMetadata("box_no", event.target.value)}
            />
          </label>
          <label>
            バインダーNo
            <input
              inputMode="numeric"
              name="binder_no"
              value={commonMetadata.binder_no}
              onChange={(event) => updateCommonMetadata("binder_no", event.target.value)}
            />
          </label>
        </div>
        <div className="summary-strip">
          <StatLine label="出力先" value={outputDir || "未設定"} />
          <StatLine label="PDF" value={`${pdfFiles.length}件`} />
          <StatLine label="ページ" value={totalPages ? `${totalPages}ページ` : "-"} />
        </div>
      </section>
    );
  }

  function renderSplitWork() {
    return (
      <section className="work-card stack" aria-label="分割">
        <PaneHeader
          title={currentPdf ? basename(currentPdf) : "PDF未選択"}
          description={currentFile ? `${currentPage} / ${currentFile.pageCount}ページ` : "PDFを取込画面で選択してください。"}
        />
        <div className="action-row">
          <button disabled={!currentFile || currentPage <= 1 || isBusy} onClick={() => void movePage(-1)} type="button">
            <IconLabel icon={ArrowLeft}>前ページ</IconLabel>
          </button>
          <button
            disabled={!currentFile || currentPage >= (currentFile?.pageCount ?? 1) || isBusy}
            onClick={() => void movePage(1)}
            type="button"
          >
            <IconLabel icon={ArrowRight}>次ページ</IconLabel>
          </button>
          <button
            className="primary"
            disabled={!currentFile || isBusy}
            onClick={() => void addSplitBeforeCurrentPage()}
            type="button"
          >
            <IconLabel icon={Split}>現在ページの前で分割</IconLabel>
          </button>
          <button disabled={!currentFile || isBusy} onClick={() => void splitEveryPage()} type="button">
            <IconLabel icon={ClipboardCheck}>1ページごとに分割</IconLabel>
          </button>
          <button disabled={!currentFile || isBusy} onClick={() => void undoLastSplit()} type="button">
            <IconLabel icon={Undo2}>最後の分割を取り消す</IconLabel>
          </button>
        </div>
        <div className="preview-frame">
          {previewDataUrl ? (
            <div className={previewLoading ? "preview-stage loading" : "preview-stage"}>
              <img alt={`PDFページプレビュー（${currentPage}ページ目）`} src={previewDataUrl} />
              {previewLoading ? <span className="preview-loading">読み込み中…</span> : null}
            </div>
          ) : previewLoading ? (
            <EmptyState icon={FileText} title="読み込み中">
              ページプレビューを読み込んでいます。
            </EmptyState>
          ) : (
            <EmptyState icon={FileText} title="プレビューなし">
              PDFを選択するとページプレビューを表示します。
            </EmptyState>
          )}
        </div>
      </section>
    );
  }

  function renderInputWork() {
    // 入力欄は個別値（segmentMetadata）をそのまま表示し、空欄時は placeholder で共通値を見せる
    const selectedOverrides = selectedSegment ? segmentMetadata[selectedSegment.key] ?? {} : {};
    const selectedPreviewName = selectedSegment ? previewFilename(selectedSegment.metadata) : null;
    return (
      <section className="work-card stack" aria-label="入力">
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
          <strong className={selectedSegment && !selectedPreviewName ? "warning" : undefined}>
            {selectedSegment ? selectedPreviewName ?? "未入力" : "-"}
          </strong>
        </div>
        <div className="action-row">
          <button disabled={!allSegments.length || isBusy} onClick={() => void resequence()} type="button">
            <IconLabel icon={ClipboardCheck}>連番を再採番</IconLabel>
          </button>
          <button
            className="primary"
            disabled={!allSegments.length || !outputDir || isBusy}
            onClick={runPreflight}
            type="button"
          >
            <IconLabel icon={ChevronRight}>{busyLabel("preflight", "出力前チェック")}</IconLabel>
          </button>
        </div>
        {selectedSegment ? (
          <div className="field-grid three">
            <label>
              箱No
              <input
                inputMode="numeric"
                name="box_no"
                placeholder={commonMetadata.box_no.trim() ? commonMetadata.box_no : undefined}
                value={selectedOverrides.box_no ?? ""}
                onChange={(event) => updateMetadata(selectedSegment, "box_no", event.target.value)}
              />
            </label>
            <label>
              バインダーNo
              <input
                inputMode="numeric"
                name="binder_no"
                placeholder={commonMetadata.binder_no.trim() ? commonMetadata.binder_no : undefined}
                value={selectedOverrides.binder_no ?? ""}
                onChange={(event) => updateMetadata(selectedSegment, "binder_no", event.target.value)}
              />
            </label>
            <label>
              連番
              <input
                inputMode="numeric"
                name="seq"
                value={selectedSegment.metadata.seq}
                onChange={(event) => updateMetadata(selectedSegment, "seq", event.target.value)}
              />
            </label>
          </div>
        ) : (
          <EmptyState
            action={
              <button onClick={() => setActiveStep(pdfFiles.length ? "split" : "import")} type="button">
                <IconLabel icon={ArrowLeft}>{pdfFiles.length ? "分割へ戻る" : "PDF取込へ戻る"}</IconLabel>
              </button>
            }
            icon={PencilLine}
            title="入力対象がありません"
          >
            {pdfFiles.length ? "分割セグメントを作成してから入力します。" : "PDFを取込んでから入力します。"}
          </EmptyState>
        )}
      </section>
    );
  }

  function renderOutputWork() {
    return (
      <section className="work-card stack" aria-label="出力">
        <PaneHeader
          title="出力確認"
          description={preflightChecks.length ? `${preflightChecks.length}件の出力予定` : "出力前チェック待ち"}
        />
        <div className="action-row">
          <button disabled={!allSegments.length || !outputDir || isBusy} onClick={runPreflight} type="button">
            <IconLabel icon={ClipboardCheck}>{busyLabel("preflight", "出力前チェック")}</IconLabel>
          </button>
          <button className="primary" disabled={!canExport || isBusy} onClick={runExport} type="button">
            <IconLabel icon={Download}>{busyLabel("export", "出力実行")}</IconLabel>
          </button>
        </div>
        <div className="summary-strip">
          <StatLine label="要修正" value={`${outputIssues}件`} />
          <StatLine label="既存あり" value={`${existingOutputs}件`} />
          <StatLine label="出力先" value={outputDir || "未設定"} />
        </div>
        {exportResult ? (
          <div className="log-box">
            <strong>出力結果</strong>
            <p>{`作成 ${exportResult.summary.created}件 / 失敗 ${exportResult.summary.failed}件`}</p>
            {exportResult.items
              .filter((item) => item.status === "failed")
              .map((item, index) => (
                <p className="danger" key={`${item.pdf_path}-${item.pages}-${index}`}>
                  {`${item.filename || item.requested_filename || basename(item.pdf_path)}: ${
                    item.error || item.messages.join(" / ") || "不明なエラー"
                  }`}
                </p>
              ))}
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
            {preflightChecks.map((check, index) => {
              const renamed =
                check.has_existing_output && Boolean(check.filename) && check.filename !== check.requested_filename;
              const duplicate = Boolean(check.requested_filename) && duplicateRequestedNames.has(check.requested_filename);
              return (
                <div
                  className={!check.ok ? "check-row error" : duplicate ? "check-row warning" : "check-row"}
                  key={`${check.pdf_path}-${check.pages}-${index}`}
                >
                  <span>{check.pages}</span>
                  <span>
                    {check.requested_filename || check.filename || "-"}
                    {renamed ? (
                      <small className="rename-note">{`→ ${check.filename} として保存（上書きしません）`}</small>
                    ) : null}
                  </span>
                  <span>{check.has_existing_output ? "あり" : "なし"}</span>
                  <span>
                    {!check.ok
                      ? check.messages.join(" / ")
                      : duplicate
                        ? "連番重複（同じ予定ファイル名があります）"
                        : "出力可能"}
                  </span>
                </div>
              );
            })}
          </div>
        ) : (
          <EmptyState action={renderShortageActions()} icon={Download} title="出力前チェック待ちです">
            {outputShortages.length ? shortageSummary() : "入力内容が揃ったら、ここで出力可否を確認します。"}
          </EmptyState>
        )}
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

  function renderRightPanel() {
    if (activeStep === "import") {
      return (
        <aside className="right-panel stack" aria-label="進捗と次アクション">
          <PaneHeader title="次アクション" description="PDF取込の完了条件" />
          <StatusCheck ok={pdfFiles.length > 0} label="PDF選択" detail={pdfFiles.length ? `${pdfFiles.length}件` : "未選択"} />
          <StatusCheck ok={Boolean(outputDir)} label="出力先" detail={outputDir || "未設定"} />
          <StatusCheck ok={Boolean(commonMetadata.box_no || commonMetadata.binder_no)} label="共通項目" detail="未入力でも後で修正可能" />
          <button className="primary wide" disabled={!canContinueFromImport} onClick={() => setActiveStep("split")} type="button">
            <IconLabel icon={ChevronRight}>分割へ進む</IconLabel>
          </button>
        </aside>
      );
    }
    if (activeStep === "split") {
      return (
        <aside className="right-panel stack" aria-label="進捗と次アクション">
          <PaneHeader title="次アクション" description="分割の確認" />
          <StatusCheck ok={Boolean(currentFile)} label="表示PDF" detail={currentFile ? basename(currentFile.path) : "未選択"} />
          <StatusCheck ok={allSegments.length > 0} label="セグメント" detail={`${allSegments.length}件`} />
          <StatusCheck ok={Boolean(currentFile)} label="ページ位置" detail={currentFile ? `${currentPage} / ${currentFile.pageCount}` : "-"} />
          <button className="primary wide" disabled={!allSegments.length} onClick={() => setActiveStep("input")} type="button">
            <IconLabel icon={ChevronRight}>入力へ進む</IconLabel>
          </button>
        </aside>
      );
    }
    if (activeStep === "input") {
      return (
        <aside className="right-panel stack" aria-label="進捗と次アクション">
          <PaneHeader title="次アクション" description="命名入力の完了条件" />
          <StatusCheck ok={allSegments.length > 0} label="入力対象" detail={`${allSegments.length}件`} />
          <StatusCheck ok={!incompleteSegments && allSegments.length > 0} label="未入力" detail={`${incompleteSegments}件`} />
          <StatusCheck ok={Boolean(outputDir)} label="出力先" detail={outputDir || "未設定"} />
          <div className="progress-count">
            <strong>{readySegments}</strong>
            <span>/ {allSegments.length}件 OK</span>
          </div>
          <button className="primary wide" disabled={!canRunPreflight || isBusy} onClick={runPreflight} type="button">
            <IconLabel icon={ChevronRight}>{busyLabel("preflight", "出力前チェック")}</IconLabel>
          </button>
        </aside>
      );
    }
    return (
      <aside className="right-panel stack" aria-label="進捗と次アクション">
        <PaneHeader title="次アクション" description="出力前チェックと実行" />
        <StatusCheck ok={preflightChecks.length > 0} label="チェック" detail={preflightChecks.length ? `${preflightChecks.length}件` : "未実行"} />
        <StatusCheck ok={outputIssues === 0 && preflightChecks.length > 0} label="要修正" detail={`${outputIssues}件`} />
        <StatusCheck
          ok={preflightChecks.length > 0}
          label="既存ファイル"
          detail={preflightChecks.length ? (existingOutputs ? `${existingOutputs}件は一意名で回避` : "既存なし") : "未確認"}
        />
        <button disabled={!canRunPreflight || isBusy} onClick={runPreflight} type="button">
          <IconLabel icon={ClipboardCheck}>{busyLabel("preflight", "再チェック")}</IconLabel>
        </button>
        <button className="primary wide" disabled={!canExport || isBusy} onClick={runExport} type="button">
          <IconLabel icon={Download}>{busyLabel("export", "出力実行")}</IconLabel>
        </button>
      </aside>
    );
  }

  return (
    <main className="app-shell">
      <header className="app-header">
        <div className="brand-row">
          <span className="brand-mark">PDF</span>
          <div>
            <p className="section-label">PDF分割命名ツール</p>
            <h1>PDF整理ツール</h1>
          </div>
        </div>
        <div className="header-actions">
          <div className="header-state-actions">
            <button disabled={isBusy} onClick={() => void loadState()} type="button">
              <IconLabel icon={RotateCcw}>{busyLabel("load", "状態を復元")}</IconLabel>
            </button>
            <button disabled={isBusy} onClick={() => void saveState()} type="button">
              <IconLabel icon={Save}>{busyLabel("save", "状態を保存")}</IconLabel>
            </button>
          </div>
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
          <div className={`status-pill ${status.tone}`} role="status">
            {status.tone === "danger" || status.tone === "warning" ? (
              <AlertTriangle aria-hidden="true" size={16} />
            ) : status.tone === "ok" ? (
              <CheckCircle2 aria-hidden="true" size={16} />
            ) : (
              <ClipboardCheck aria-hidden="true" size={16} />
            )}
            <span>{status.message}</span>
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
              onClick={() => setActiveStep(step.id)}
              type="button"
            >
              <span className="step-index">{index + 1}</span>
              <span className="step-copy">
                <strong>
                  <Icon aria-hidden="true" size={16} strokeWidth={2.1} />
                  {step.label}
                </strong>
                <small>{step.hint}</small>
              </span>
              <span className={`step-badge ${state}`}>{stepStateLabel(state)}</span>
            </button>
          );
        })}
      </nav>

      <section className="overview-strip" aria-label="作業状況">
        <StatLine label="PDF" value={`${pdfFiles.length}件`} />
        <StatLine label="分割" value={`${allSegments.length}件`} />
        <StatLine
          label="入力"
          tone={allSegments.length ? undefined : "warning"}
          value={allSegments.length ? `${readySegments}件 OK` : "未確認"}
        />
        <StatLine label="出力先" tone={outputDir ? undefined : "warning"} value={outputDir ? "設定済み" : "未設定"} />
      </section>

      <section className="task-layout" aria-label="PDF整理ワークスペース">
        {renderLeftPane()}
        {renderWorkPane()}
        {renderRightPanel()}
      </section>
    </main>
  );
}

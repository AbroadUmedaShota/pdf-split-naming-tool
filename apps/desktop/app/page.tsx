"use client";

import { open } from "@tauri-apps/plugin-dialog";
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
  type SidecarPreflightResponse,
  type SidecarPreviewResponse,
  type SidecarResponse,
  type SidecarSegment
} from "../lib/sidecar";
import { resolveMissingSavedPdfRestore, restorableInputPaths } from "../lib/restore-state";
import { missingMetadata, previewFilename } from "../lib/filename-policy";
import { isOutputCheckOk, outputDetailStateText, outputIssueCount, outputListStateText } from "../lib/output-state";
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

type StepState = "active" | "done" | "attention" | "idle";
type UpdateState = "idle" | "checking" | "current" | "available" | "installing" | "installed" | "error";

const steps: Array<{ id: StepId; label: string; hint: string; icon: LucideIcon }> = [
  { id: "import", label: "PDF取込", hint: "PDF / 出力先", icon: FileText },
  { id: "split", label: "分割", hint: "ページ範囲", icon: Split },
  { id: "input", label: "入力", hint: "箱No / 連番", icon: PencilLine },
  { id: "output", label: "出力", hint: "チェック / 実行", icon: Download }
];

const emptyCommonMetadata = { box_no: "", binder_no: "" };

function basename(path: string): string {
  return path.split(/[\\/]/).filter(Boolean).pop() ?? path;
}

function sidecarError(response: SidecarResponse): string {
  return "error" in response ? response.error : "Sidecar response is not usable for this operation.";
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

export default function Page() {
  const [activeStep, setActiveStep] = useState<StepId>("import");
  const [pdfFiles, setPdfFiles] = useState<PdfFile[]>([]);
  const [currentPdf, setCurrentPdf] = useState("");
  const [currentPage, setCurrentPage] = useState(1);
  const [previewDataUrl, setPreviewDataUrl] = useState("");
  const [outputDir, setOutputDir] = useState("");
  const [commonMetadata, setCommonMetadata] = useState<Record<string, string>>(emptyCommonMetadata);
  const [splitPointsByPdf, setSplitPointsByPdf] = useState<Record<string, number[]>>({});
  const [segmentMetadata, setSegmentMetadata] = useState<SegmentMetadata>({});
  const [selectedSegmentKey, setSelectedSegmentKey] = useState("");
  const [preflightChecks, setPreflightChecks] = useState<SidecarOutputCheck[]>([]);
  const [exportResult, setExportResult] = useState<SidecarExportResponse | null>(null);
  const [status, setStatus] = useState("PDFを選択してください。");
  const [currentVersion, setCurrentVersion] = useState("0.1.0");
  const [updateState, setUpdateState] = useState<UpdateState>("idle");
  const [updateMessage, setUpdateMessage] = useState("更新未確認");
  const [updateProgress, setUpdateProgress] = useState("");
  const [availableUpdate, setAvailableUpdate] = useState<AppUpdate | null>(null);
  const previewRequestGateRef = useRef(createPreviewRequestGate());
  const workspaceRequestGateRef = useRef(createPreviewRequestGate());

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
  const outputIssues = outputIssueCount(preflightChecks);
  const existingOutputs = preflightChecks.filter((check) => check.has_existing_output).length;
  const canContinueFromImport = pdfFiles.length > 0 && Boolean(outputDir);
  const canRunPreflight = allSegments.length > 0 && Boolean(outputDir);
  const canExport = preflightChecks.length > 0 && outputIssues === 0;

  function clearOutputState(): void {
    setPreflightChecks([]);
    setExportResult(null);
  }

  function updateCurrentPdfSplitPoints(nextPointsFor: (currentPoints: number[]) => number[]): void {
    if (!currentFile) {
      return;
    }

    const pdfPath = currentFile.path;
    const pageCount = currentFile.pageCount;
    const previousPoints = splitPointsFor(pageCount, splitPointsByPdf[pdfPath]);
    const nextPoints = splitPointsFor(pageCount, nextPointsFor(previousPoints));

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

  function invalidateWorkspaceAndPreviewRequests(): void {
    invalidateWorkspaceRequests();
    invalidatePreviewRequests();
  }

  async function loadPreview(pdfPath: string, pageNo: number): Promise<void> {
    const requestId = previewRequestGateRef.current.next();
    const cachedPreview = previewCache.get(pdfPath, pageNo);
    if (cachedPreview) {
      setPreviewDataUrl(cachedPreview.imageDataUrl);
      setCurrentPage(cachedPreview.pageNo);
      return;
    }
    const response = await invokeSidecar({ command: "page_preview", pdf_path: pdfPath, page_no: pageNo });
    if (!previewRequestGateRef.current.isCurrent(requestId)) {
      return;
    }
    if (!response.ok || response.command !== "page_preview") {
      throw new Error(response.ok ? "プレビューを取得できませんでした。" : sidecarError(response));
    }
    const preview = response as SidecarPreviewResponse;
    previewCache.set(pdfPath, pageNo, {
      imageDataUrl: preview.image_data_url,
      pageNo: preview.page_no
    });
    setPreviewDataUrl(preview.image_data_url);
    setCurrentPage(preview.page_no);
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

  async function removePdf(path: string): Promise<void> {
    const remaining = pdfFiles.filter((file) => file.path !== path);
    invalidateWorkspaceAndPreviewRequests();
    previewCache.clearPdf(path);
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
    clearOutputState();
    setStatus("PDF一覧をクリアしました。");
  }

  function resetOutputDir(): void {
    invalidateWorkspaceRequests();
    setOutputDir("");
    clearOutputState();
    setStatus("出力先をリセットしました。");
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
    setStatus(`${currentPage}ページの前に分割を追加しました。`);
  }

  function undoLastSplit(): void {
    invalidateWorkspaceRequests();
    if (!currentFile) {
      return;
    }
    clearOutputState();
    updateCurrentPdfSplitPoints((currentPoints) => currentPoints.slice(0, -1));
    setStatus("最後の分割を取り消しました。");
  }

  function splitEveryPage(): void {
    invalidateWorkspaceRequests();
    if (!currentFile) {
      return;
    }
    clearOutputState();
    updateCurrentPdfSplitPoints(() =>
      Array.from({ length: Math.max(0, currentFile.pageCount - 1) }, (_value, index) => index + 2)
    );
    setStatus("1ページごとの分割にしました。");
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

  function resequence(): void {
    invalidateWorkspaceRequests();
    clearOutputState();
    setSegmentMetadata((current) => {
      const next = { ...current };
      allSegments.forEach((segment, index) => {
        next[segment.key] = { ...(next[segment.key] ?? {}), seq: String(index + 1) };
      });
      return next;
    });
    setStatus("連番を再採番しました。");
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
    try {
      const response = await invokeSidecar({ command: "preflight", output_dir: outputDir, segments: requestSegments() });
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
    }
  }

  async function runExport(): Promise<void> {
    try {
      const response = await invokeSidecar({ command: "export", output_dir: outputDir, segments: requestSegments() });
      if (response.command !== "export") {
        throw new Error(response.ok ? "出力に失敗しました。" : sidecarError(response));
      }
      const result = response as SidecarExportResponse;
      setExportResult(result);
      setPreflightChecks(result.items);
      setStatus(result.ok ? "出力が完了しました。" : "出力結果を確認してください。");
    } catch (error) {
      setStatus(`出力エラー: ${String(error)}`);
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
      setPdfFiles(loaded);
      setOutputDir(state.output_dir ?? "");
      setSplitPointsByPdf(state.split_points_by_pdf ?? {});
      setSegmentMetadata(state.segment_metadata ?? {});
      setCommonMetadata({ ...emptyCommonMetadata, ...(state.common_metadata ?? {}) });
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
              allSegments.map((segment) => (
                <button
                  className={segment.key === selectedSegmentKey ? "list-row selected" : "list-row"}
                  key={segment.key}
                  onClick={() => setSelectedSegmentKey(segment.key)}
                  type="button"
                >
                  <span>
                    <strong>{segment.pages}ページ</strong>
                    <small>{basename(segment.pdfPath)}</small>
                  </span>
                  <span className="row-meta">{previewFilename(segment.metadata)}</span>
                </button>
              ))
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
                  <small>{check.pages}ページ</small>
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
              <button disabled={!canRunPreflight} onClick={runPreflight} type="button">
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
      <section className="work-card stack" aria-label="PDF取込">
        <PaneHeader title="取込設定" description="対象PDF、出力先、共通項目をここで揃えます。" />
        <div className="action-row">
          <button className="primary" onClick={choosePdfs} type="button">
            <IconLabel icon={Upload}>PDFを選択</IconLabel>
          </button>
          <button onClick={chooseOutputDir} type="button">
            <IconLabel icon={FolderOpen}>出力フォルダ</IconLabel>
          </button>
          <button disabled={!outputDir} onClick={resetOutputDir} type="button">
            <IconLabel icon={XCircle}>出力先リセット</IconLabel>
          </button>
          <button onClick={loadState} type="button">
            <IconLabel icon={RotateCcw}>状態を復元</IconLabel>
          </button>
          <button onClick={saveState} type="button">
            <IconLabel icon={Save}>状態を保存</IconLabel>
          </button>
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
          <button disabled={!currentFile || currentPage <= 1} onClick={() => void movePage(-1)} type="button">
            <IconLabel icon={ArrowLeft}>前ページ</IconLabel>
          </button>
          <button
            disabled={!currentFile || currentPage >= (currentFile?.pageCount ?? 1)}
            onClick={() => void movePage(1)}
            type="button"
          >
            <IconLabel icon={ArrowRight}>次ページ</IconLabel>
          </button>
          <button className="primary" disabled={!currentFile} onClick={addSplitBeforeCurrentPage} type="button">
            <IconLabel icon={Split}>現在ページの前で分割</IconLabel>
          </button>
          <button disabled={!currentFile} onClick={splitEveryPage} type="button">
            <IconLabel icon={ClipboardCheck}>1ページごとに分割</IconLabel>
          </button>
          <button disabled={!currentFile} onClick={undoLastSplit} type="button">
            <IconLabel icon={Undo2}>最後の分割を取り消す</IconLabel>
          </button>
        </div>
        <div className="preview-frame">
          {previewDataUrl ? (
            <img alt="PDFページプレビュー" src={previewDataUrl} />
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
          <strong>{selectedSegment ? previewFilename(selectedSegment.metadata) : "-"}</strong>
        </div>
        <div className="action-row">
          <button className="primary" disabled={!allSegments.length} onClick={resequence} type="button">
            <IconLabel icon={ClipboardCheck}>連番を再採番</IconLabel>
          </button>
          <button disabled={!allSegments.length || !outputDir} onClick={runPreflight} type="button">
            <IconLabel icon={ChevronRight}>出力前チェック</IconLabel>
          </button>
        </div>
        {selectedSegment ? (
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
                onChange={(event) => updateMetadata(selectedSegment, "seq", event.target.value)}
              />
            </label>
          </div>
        ) : (
          <EmptyState icon={PencilLine} title="入力対象がありません">
            分割セグメントを作成してから入力します。
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
          <button disabled={!allSegments.length || !outputDir} onClick={runPreflight} type="button">
            <IconLabel icon={ClipboardCheck}>出力前チェック</IconLabel>
          </button>
          <button className="primary" disabled={!canExport} onClick={runExport} type="button">
            <IconLabel icon={Download}>出力実行</IconLabel>
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
          <button className="primary wide" disabled={!canRunPreflight} onClick={runPreflight} type="button">
            <IconLabel icon={ChevronRight}>出力前チェック</IconLabel>
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
        <button disabled={!canRunPreflight} onClick={runPreflight} type="button">
          <IconLabel icon={ClipboardCheck}>再チェック</IconLabel>
        </button>
        <button className="primary wide" disabled={!canExport} onClick={runExport} type="button">
          <IconLabel icon={Download}>出力実行</IconLabel>
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
        <StatLine label="入力" value={allSegments.length ? `${readySegments}件 OK` : "未確認"} />
        <StatLine label="出力先" value={outputDir ? "設定済み" : "未設定"} />
      </section>

      <section className="task-layout" aria-label="PDF整理ワークスペース">
        {renderLeftPane()}
        {renderWorkPane()}
        {renderRightPanel()}
      </section>
    </main>
  );
}

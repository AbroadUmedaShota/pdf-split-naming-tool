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
  PencilLine,
  RotateCcw,
  Save,
  Split,
  Undo2,
  Upload,
  type LucideIcon
} from "lucide-react";
import { type ReactNode, useMemo, useState } from "react";
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

const steps: Array<{ id: StepId; label: string; hint: string; icon: LucideIcon }> = [
  { id: "import", label: "PDF取込", hint: "PDF / 出力先", icon: FileText },
  { id: "split", label: "分割", hint: "ページ範囲", icon: Split },
  { id: "input", label: "入力", hint: "箱No / 連番", icon: PencilLine },
  { id: "output", label: "出力", hint: "チェック / 実行", icon: Download }
];

const emptyCommonMetadata = { box_no: "", binder_no: "" };
const requiredMetadata = ["box_no", "binder_no", "seq"] as const;
const invalidFilenameChars = /[<>:"/\\|?*]/g;

function basename(path: string): string {
  return path.split(/[\\/]/).filter(Boolean).pop() ?? path;
}

function segmentKey(pdfPath: string, startPage: number, endPage: number): string {
  return `${pdfPath}#${startPage}-${endPage}`;
}

function pageLabel(startPage: number, endPage: number): string {
  return startPage === endPage ? `${startPage}` : `${startPage}-${endPage}`;
}

function padMetadata(value: string, length: number): string {
  const trimmed = value.trim();
  return trimmed.length >= length ? trimmed : trimmed.padStart(length, "0");
}

function sanitizeFilename(filename: string): string {
  const sanitized = filename.replace(invalidFilenameChars, "_").trim().replace(/[. ]+$/g, "").replace(/\s+/g, " ");
  return sanitized || "output.pdf";
}

function previewFilename(metadata: Record<string, string>): string {
  if (missingMetadata(metadata).length) {
    return "未入力";
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
          ...(segmentMetadata[key] ?? {})
        }
      };
    });
  });
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
  const [preflightChecks, setPreflightChecks] = useState<SidecarOutputCheck[]>([]);
  const [exportResult, setExportResult] = useState<SidecarExportResponse | null>(null);
  const [status, setStatus] = useState("PDFを選択してください。");

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
  const canContinueFromImport = pdfFiles.length > 0 && Boolean(outputDir);
  const canRunPreflight = allSegments.length > 0 && Boolean(outputDir);
  const canExport = preflightChecks.length > 0 && outputIssues === 0;

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

  async function loadPreview(pdfPath: string, pageNo: number): Promise<void> {
    const response = await invokeSidecar({ command: "page_preview", pdf_path: pdfPath, page_no: pageNo });
    if (!response.ok || response.command !== "page_preview") {
      throw new Error(response.ok ? "プレビューを取得できませんでした。" : sidecarError(response));
    }
    const preview = response as SidecarPreviewResponse;
    setPreviewDataUrl(preview.image_data_url);
    setCurrentPage(preview.page_no);
  }

  async function choosePdfs(): Promise<void> {
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
      setPdfFiles((existing) => {
        const byPath = new Map(existing.map((file) => [file.path, file]));
        for (const file of loaded) {
          byPath.set(file.path, file);
        }
        return [...byPath.values()];
      });
      setCurrentPdf(loaded[0].path);
      setCurrentPage(1);
      await loadPreview(loaded[0].path, 1);
      setStatus(`${loaded.length}件のPDFを読み込みました。`);
    } catch (error) {
      setStatus(`PDF取込エラー: ${String(error)}`);
    }
  }

  async function chooseOutputDir(): Promise<void> {
    const selected = await open({ directory: true, multiple: false });
    if (typeof selected === "string") {
      setOutputDir(selected);
      setStatus("出力フォルダを設定しました。");
    }
  }

  async function selectPdf(path: string): Promise<void> {
    setCurrentPdf(path);
    setCurrentPage(1);
    try {
      await loadPreview(path, 1);
    } catch (error) {
      setStatus(`プレビューエラー: ${String(error)}`);
    }
  }

  async function movePage(offset: number): Promise<void> {
    if (!currentFile) {
      return;
    }
    const nextPage = Math.max(1, Math.min(currentFile.pageCount, currentPage + offset));
    try {
      await loadPreview(currentFile.path, nextPage);
    } catch (error) {
      setStatus(`ページ移動エラー: ${String(error)}`);
    }
  }

  function addSplitBeforeCurrentPage(): void {
    if (!currentFile || currentPage <= 1) {
      setStatus("先頭ページの前では分割できません。");
      return;
    }
    setSplitPointsByPdf((current) => ({
      ...current,
      [currentFile.path]: splitPointsFor(currentFile.pageCount, [...(current[currentFile.path] ?? []), currentPage])
    }));
    setStatus(`${currentPage}ページの前に分割を追加しました。`);
  }

  function undoLastSplit(): void {
    if (!currentFile) {
      return;
    }
    setSplitPointsByPdf((current) => {
      const points = splitPointsFor(currentFile.pageCount, current[currentFile.path]);
      return { ...current, [currentFile.path]: points.slice(0, -1) };
    });
    setStatus("最後の分割を取り消しました。");
  }

  function splitEveryPage(): void {
    if (!currentFile) {
      return;
    }
    setSplitPointsByPdf((current) => ({
      ...current,
      [currentFile.path]: Array.from({ length: Math.max(0, currentFile.pageCount - 1) }, (_value, index) => index + 2)
    }));
    setStatus("1ページごとの分割にしました。");
  }

  function updateMetadata(segment: SegmentView, key: string, value: string): void {
    setSegmentMetadata((current) => ({
      ...current,
      [segment.key]: {
        ...(current[segment.key] ?? {}),
        [key]: value
      }
    }));
  }

  function resequence(): void {
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
    const response = await invokeSidecar({ command: "state_load" });
    if (!response.ok || response.command !== "state_load") {
      setStatus(response.ok ? "状態読込に失敗しました。" : `状態読込エラー: ${sidecarError(response)}`);
      return;
    }
    const state = response.state as Partial<AppPersistedState>;
    if (!Array.isArray(state.input_paths) || !state.input_paths.length) {
      setStatus("保存済み状態はありません。");
      return;
    }
    try {
      const loaded = await Promise.all(state.input_paths.map((path) => loadPdfInfo(path)));
      setPdfFiles(loaded);
      setOutputDir(state.output_dir ?? "");
      setSplitPointsByPdf(state.split_points_by_pdf ?? {});
      setSegmentMetadata(state.segment_metadata ?? {});
      setCommonMetadata({ ...emptyCommonMetadata, ...(state.common_metadata ?? {}) });
      setCurrentPdf(state.current_pdf || loaded[0].path);
      setCurrentPage(state.current_page ?? 1);
      await loadPreview(state.current_pdf || loaded[0].path, state.current_page ?? 1);
      setStatus("状態を復元しました。");
    } catch (error) {
      setStatus(`状態復元エラー: ${String(error)}`);
    }
  }

  const statusTone = status.includes("エラー")
    ? "danger"
    : status.includes("修正") || status.includes("不足")
      ? "warning"
      : status.includes("完了") || status.includes("できます")
        ? "ok"
        : "";

  return (
    <main className="app-shell">
      <aside className="rail" aria-label="作業ステップ">
        <div className="brand">
          <span className="brand-mark">PDF</span>
          <div>
            <h1>PDF整理ツール</h1>
            <p>Local Desktop</p>
          </div>
        </div>
        <nav className="step-list">
          {steps.map((step, index) => {
            const state = stepState(step.id);
            const Icon = step.icon;
            return (
              <button
                aria-current={activeStep === step.id ? "step" : undefined}
                className={`step ${state}`}
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
                  <span>{step.hint}</span>
                </span>
                <span className={`step-badge ${state}`}>{stepStateLabel(state)}</span>
              </button>
            );
          })}
        </nav>
      </aside>

      <section className="workspace" aria-label="PDF整理ワークスペース">
        <header className="topbar">
          <div>
            <p className="section-label">PDF分割命名ツール</p>
            <h2>{steps.find((step) => step.id === activeStep)?.label}</h2>
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
        </header>

        <section className="work-summary" aria-label="作業状況">
          <div>
            <span>PDF</span>
            <strong>{pdfFiles.length}件</strong>
            <small>{totalPages ? `${totalPages}ページ` : "未選択"}</small>
          </div>
          <div>
            <span>分割</span>
            <strong>{allSegments.length}件</strong>
            <small>{currentFile ? `${basename(currentFile.path)} を表示中` : "PDF未選択"}</small>
          </div>
          <div className={incompleteSegments ? "needs-attention" : ""}>
            <span>入力</span>
            <strong>{allSegments.length ? `${readySegments}件 OK` : "未確認"}</strong>
            <small>{allSegments.length ? (incompleteSegments ? `${incompleteSegments}件 未入力` : "未入力なし") : "入力対象なし"}</small>
          </div>
          <div className={outputDir ? "" : "needs-attention"}>
            <span>出力先</span>
            <strong>{outputDir ? "設定済み" : "未設定"}</strong>
            <small>{outputDir || "フォルダを選択"}</small>
          </div>
        </section>

        {activeStep === "import" && (
          <section className="panel stack" aria-label="PDF取込">
            <div className="panel-heading">
              <div>
                <h3>取込設定</h3>
                <p>対象PDF、出力先、共通項目をここで揃えます。</p>
              </div>
              <button disabled={!canContinueFromImport} onClick={() => setActiveStep("split")} type="button">
                <IconLabel icon={ChevronRight}>分割へ進む</IconLabel>
              </button>
            </div>
            <div className="action-row">
              <button className="primary" onClick={choosePdfs} type="button">
                <IconLabel icon={Upload}>PDFを選択</IconLabel>
              </button>
              <button onClick={chooseOutputDir} type="button">
                <IconLabel icon={FolderOpen}>出力フォルダ</IconLabel>
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
                <input
                  value={commonMetadata.box_no}
                  onChange={(event) => setCommonMetadata((current) => ({ ...current, box_no: event.target.value }))}
                />
              </label>
              <label>
                バインダーNo
                <input
                  value={commonMetadata.binder_no}
                  onChange={(event) => setCommonMetadata((current) => ({ ...current, binder_no: event.target.value }))}
                />
              </label>
            </div>
            <div className="summary-grid">
              <div>
                <span>出力先</span>
                <strong>{outputDir || "未設定"}</strong>
              </div>
              <div>
                <span>PDF</span>
                <strong>{pdfFiles.length}件</strong>
              </div>
              <div>
                <span>分割</span>
                <strong>{allSegments.length}件</strong>
              </div>
            </div>
            {pdfFiles.length ? (
              <div className="list">
                {pdfFiles.map((file) => (
                  <button
                    className={file.path === currentPdf ? "list-row selected" : "list-row"}
                    key={file.path}
                    onClick={() => void selectPdf(file.path)}
                    type="button"
                  >
                    <span>
                      <strong>{basename(file.path)}</strong>
                      <small>{file.path}</small>
                    </span>
                    <span>{file.pageCount}ページ</span>
                  </button>
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
          </section>
        )}

        {activeStep === "split" && (
          <section className="split-layout" aria-label="分割">
            <div className="panel stack">
              <div className="panel-heading">
                <div>
                  <h3>{currentPdf ? basename(currentPdf) : "PDF未選択"}</h3>
                  <p>{currentFile ? `${currentPage} / ${currentFile.pageCount}ページ` : "PDFを取込画面で選択してください。"}</p>
                </div>
                <button disabled={!allSegments.length} onClick={() => setActiveStep("input")} type="button">
                  <IconLabel icon={ChevronRight}>入力へ進む</IconLabel>
                </button>
              </div>
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
            </div>
            <aside className="panel stack">
              <div className="panel-heading compact-heading">
                <div>
                  <h3>分割一覧</h3>
                  <p>{allSegments.length ? `${allSegments.length}件` : "未作成"}</p>
                </div>
              </div>
              <div className="list compact">
                {allSegments.length ? (
                  allSegments.map((segment) => (
                    <button
                      className={segment.key === selectedSegmentKey ? "list-row selected" : "list-row"}
                      key={segment.key}
                      onClick={() => setSelectedSegmentKey(segment.key)}
                      type="button"
                    >
                      <span>
                        <strong>{basename(segment.pdfPath)}</strong>
                        <small>{previewFilename(segment.metadata)}</small>
                      </span>
                      <span>{segment.pages}ページ</span>
                    </button>
                  ))
                ) : (
                  <EmptyState icon={Split} title="分割なし">
                    PDFを選択するとページ範囲が表示されます。
                  </EmptyState>
                )}
              </div>
            </aside>
          </section>
        )}

        {activeStep === "input" && (
          <section className="panel stack" aria-label="入力">
            <div className="panel-heading">
              <div>
                <h3>命名入力</h3>
                <p>
                  {selectedSegment
                    ? `${basename(selectedSegment.pdfPath)} / ${selectedSegment.pages}ページ`
                    : "分割セグメントがありません。"}
                </p>
              </div>
              <div className="filename-preview">
                <span>出力名</span>
                <strong>{selectedSegment ? previewFilename(selectedSegment.metadata) : "-"}</strong>
              </div>
            </div>
            <div className="action-row">
              <button className="primary" disabled={!allSegments.length} onClick={resequence} type="button">
                <IconLabel icon={ClipboardCheck}>連番を再採番</IconLabel>
              </button>
              <button disabled={!allSegments.length || !outputDir} onClick={runPreflight} type="button">
                <IconLabel icon={ChevronRight}>出力前チェック</IconLabel>
              </button>
            </div>
            {selectedSegment && (
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
            )}
            {allSegments.length ? (
              <div className="table input-table">
                <div className="table-head">
                  <span>PDF</span>
                  <span>ページ</span>
                  <span>箱No</span>
                  <span>バインダー</span>
                  <span>連番</span>
                  <span>出力名</span>
                  <span>状態</span>
                </div>
                {allSegments.map((segment) => {
                  const missing = missingMetadata(segment.metadata);
                  return (
                    <button
                      className={segment.key === selectedSegment?.key ? "table-row selected" : "table-row"}
                      key={segment.key}
                      onClick={() => setSelectedSegmentKey(segment.key)}
                      type="button"
                    >
                      <span>{basename(segment.pdfPath)}</span>
                      <span>{segment.pages}</span>
                      <span>{segment.metadata.box_no || "-"}</span>
                      <span>{segment.metadata.binder_no || "-"}</span>
                      <span>{segment.metadata.seq || "-"}</span>
                      <span>{previewFilename(segment.metadata)}</span>
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
          </section>
        )}

        {activeStep === "output" && (
          <section className="panel stack" aria-label="出力">
            <div className="panel-heading">
              <div>
                <h3>出力確認</h3>
                <p>{preflightChecks.length ? `${preflightChecks.length}件の出力予定` : "出力前チェック待ち"}</p>
              </div>
              <div className={!preflightChecks.length || outputIssues ? "check-summary warning" : "check-summary"}>
                <strong>{preflightChecks.length ? (outputIssues ? `${outputIssues}件 要修正` : "出力可能") : "未確認"}</strong>
                <span>{outputDir || "出力先未設定"}</span>
              </div>
            </div>
            <div className="action-row">
              <button disabled={!allSegments.length || !outputDir} onClick={runPreflight} type="button">
                <IconLabel icon={ClipboardCheck}>出力前チェック</IconLabel>
              </button>
              <button
                className="primary"
                disabled={!canExport}
                onClick={runExport}
                type="button"
              >
                <IconLabel icon={Download}>出力実行</IconLabel>
              </button>
            </div>
            {exportResult && (
              <div className="summary-grid">
                <div>
                  <span>作成</span>
                  <strong>{exportResult.summary.created}件</strong>
                </div>
                <div>
                  <span>失敗</span>
                  <strong>{exportResult.summary.failed}件</strong>
                </div>
              </div>
            )}
            {preflightChecks.length ? (
              <div className="table output-table">
                <div className="table-head">
                  <span>ページ</span>
                  <span>予定ファイル名</span>
                  <span>既存</span>
                  <span>状態</span>
                </div>
                {preflightChecks.map((check, index) => (
                  <div
                    className={check.ok ? "table-row" : "table-row error"}
                    key={`${check.pdf_path}-${check.pages}-${index}`}
                  >
                    <span>{check.pages}</span>
                    <span>{check.filename || check.requested_filename || "-"}</span>
                    <span>{check.has_existing_output ? "あり" : "なし"}</span>
                    <span>{check.ok ? "出力可能" : check.messages.join(" / ")}</span>
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
                title="出力前チェック待ちです"
              >
                入力内容が揃ったら、ここで出力可否を確認します。
              </EmptyState>
            )}
          </section>
        )}
      </section>
    </main>
  );
}

import {
  SIDE_CAR_COMMANDS,
  type SidecarCommand,
  type SidecarRequest
} from "../lib/sidecar";

const steps = [
  { label: "PDF取込", state: "待機", detail: "ファイル選択とプリセット読込" },
  { label: "ページ整理", state: "準備中", detail: "ページ順、抽出、回転" },
  { label: "項目入力", state: "準備中", detail: "候補確認と手入力" },
  { label: "出力確認", state: "準備中", detail: "重複、既存、未入力検査" },
  { label: "履歴", state: "準備中", detail: "ローカル出力記録" }
];

const sidecarSamples: Array<{ command: SidecarCommand; request: SidecarRequest }> = [
  { command: "presets", request: { command: "presets", work_dir: "." } },
  { command: "pdf_info", request: { command: "pdf_info", pdf_path: "sample.pdf" } },
  { command: "page_text", request: { command: "page_text", pdf_path: "sample.pdf", page_no: 1 } }
];

export default function Page() {
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
          {steps.map((step, index) => (
            <button className={index === 0 ? "step active" : "step"} key={step.label}>
              <span className="step-index">{index + 1}</span>
              <span>
                <strong>{step.label}</strong>
                <small>{step.state}</small>
              </span>
            </button>
          ))}
        </nav>
      </aside>

      <section className="workspace" aria-label="PDF整理ワークスペース">
        <header className="topbar">
          <div>
            <p className="section-label">Desktop modernization</p>
            <h2>Tauri + Next.js shell</h2>
          </div>
          <div className="status-pill">sidecar ready: {SIDE_CAR_COMMANDS.length} commands</div>
        </header>

        <div className="tool-grid">
          <section className="panel import-panel" aria-label="PDF取込">
            <div className="panel-heading">
              <h3>PDF取込</h3>
              <span>未接続</span>
            </div>
            <div className="drop-zone">
              <strong>sample.pdf</strong>
              <span>3 pages / text layer detected</span>
            </div>
            <dl className="compact-list">
              <div>
                <dt>プリセット</dt>
                <dd>yoshida-elsis</dd>
              </div>
              <div>
                <dt>履歴</dt>
                <dd>0 runs</dd>
              </div>
            </dl>
          </section>

          <section className="panel page-panel" aria-label="ページ整理">
            <div className="panel-heading">
              <h3>ページ整理</h3>
              <span>preview shell</span>
            </div>
            <div className="page-row selected">
              <span>1</span>
              <p>表紙 / 取込候補</p>
            </div>
            <div className="page-row">
              <span>2</span>
              <p>契約書本文</p>
            </div>
            <div className="page-row">
              <span>3</span>
              <p>添付資料</p>
            </div>
          </section>

          <section className="panel detail-panel" aria-label="項目入力">
            <div className="panel-heading">
              <h3>項目入力</h3>
              <span>候補表示</span>
            </div>
            <div className="field-grid">
              <label>
                箱No
                <input readOnly value="01" />
              </label>
              <label>
                バインダーNo
                <input readOnly value="02" />
              </label>
              <label>
                連番
                <input readOnly value="003" />
              </label>
            </div>
            <div className="candidate-strip">
              <button>Acme Inc</button>
              <button>Lease Agreement</button>
              <button>2026-05-25</button>
            </div>
          </section>

          <section className="panel preflight-panel" aria-label="出力前確認">
            <div className="panel-heading">
              <h3>出力前確認</h3>
              <span>ready</span>
            </div>
            <div className="result-row ok">
              <strong>01_02_003.pdf</strong>
              <span>出力可能</span>
            </div>
            <div className="result-row">
              <strong>履歴</strong>
              <span>ローカル保存</span>
            </div>
          </section>

          <section className="panel contract-panel" aria-label="Sidecar契約">
            <div className="panel-heading">
              <h3>Sidecar API</h3>
              <span>JSON</span>
            </div>
            <div className="command-list">
              {sidecarSamples.map((sample) => (
                <code key={sample.command}>{JSON.stringify(sample.request)}</code>
              ))}
            </div>
          </section>
        </div>
      </section>
    </main>
  );
}

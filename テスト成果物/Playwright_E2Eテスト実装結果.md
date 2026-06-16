# Playwright E2Eテスト実装結果

## 1. 実装対象

- 対象アプリ: apps/desktop（Next.js）http://localhost:3000
- 実行手段: STEP1取込E2Eハーネス（`?e2e=step1`）と dev preview モード（`?dev=<stepId>`）。Tauri/Python サイドカー無しで、ファイル選択・sidecar応答を差し替えたUI状態遷移と、dev preview の決定論的UIを確認する。
- 実装範囲: STEP1優先テストケース TC-E2E-S1-001〜006 / TC-E2E-S1-011、および E2E自動テストケース TC-E2E-001〜018 のうち dev preview で決定論的に再現できるもの。

## 2. 参照資料

- テスト成果物/テストケース_E2E自動.md
- テスト成果物/テストケース_質問待ち.md（TC-E2E-001〜018）
- テスト成果物/テスト設計.md（3.10節 E2Eレーン・TD043-050/047b/056/068/069）
- テスト成果物/テスト設計_質問票.md（DQ03）
- apps/desktop/app/page.tsx（dev preview 挙動・セレクタ・各操作ハンドラの早期 return）

## 3. Playwright構成

| 項目 | 内容 |
|---|---|
| Playwright バージョン | @playwright/test 1.60.0（導入済み・chromium 導入済み） |
| 設定ファイル | apps/desktop/playwright.config.js（新規・ESM） |
| testDir | apps/desktop/e2e |
| baseURL | http://localhost:3000 |
| プロジェクト | chromium のみ |
| webServer | `npm run dev`（cwd=apps/desktop）を自動起動/停止。`url=http://localhost:3000`、`reuseExistingServer: !CI`、timeout 240s。テスト後に dev server を自動停止 |
| reporter | list ＋ json（`e2e/.report/results.json`） |
| trace/screenshot/video | retain-on-failure / only-on-failure / retain-on-failure |
| 実行スクリプト | `npm run test:e2e`（= `playwright test`） |
| ヘルパ | apps/desktop/e2e/helpers.js（openDevStep / countSearchHighlights） |

`package.json` は `"type": "module"` のため、config・helpers・spec はすべて ESM（import/export）で記述。製品依存の新規追加なし（@playwright/test は導入済み）。

## 4. 実装したテスト

| テストケースID | テスト名 | 実装ファイル | 対象 | テストレベル/タイプ | 仕様 | リスクID | 状態 |
|---|---|---|---|---|---|---|---|
| TC-E2E-S1-001 | STEP1初期表示でPDF未選択状態とPDF選択ボタンが表示される | apps/desktop/e2e/desktop-shell.e2e.spec.js | http://localhost:3000/?e2e=step1 | E2E | E2Eテスト一覧_STEP1優先.md | R-STEP1 | 作成済み |
| TC-E2E-S1-002 | PDF選択操作でファイル選択処理が呼ばれる | apps/desktop/e2e/desktop-shell.e2e.spec.js | http://localhost:3000/?e2e=step1 | E2E | E2Eテスト一覧_STEP1優先.md | R-STEP1 | 作成済み |
| TC-E2E-S1-003 | PDF選択後にPDF一覧・ページ数・プレビューが反映される | apps/desktop/e2e/desktop-shell.e2e.spec.js | http://localhost:3000/?e2e=step1 | E2E | E2Eテスト一覧_STEP1優先.md | R-STEP1 | 作成済み |
| TC-E2E-S1-004 | PDFと出力先の設定後にSTEP2へ進める | apps/desktop/e2e/desktop-shell.e2e.spec.js | http://localhost:3000/?e2e=step1 | E2E | E2Eテスト一覧_STEP1優先.md | R-STEP1 | 作成済み |
| TC-E2E-S1-005 | PDF選択キャンセル時、一覧とステータスが壊れない | apps/desktop/e2e/desktop-shell.e2e.spec.js | http://localhost:3000/?e2e=step1 | E2E | E2Eテスト一覧_STEP1優先.md | R-STEP1 | 作成済み |
| TC-E2E-S1-006 | pdf_info失敗時、エラー表示となり一覧へ不正反映しない | apps/desktop/e2e/desktop-shell.e2e.spec.js | http://localhost:3000/?e2e=step1 | E2E | E2Eテスト一覧_STEP1優先.md | R-STEP1 | 作成済み |
| TC-E2E-S1-011 | 複数PDF選択時に一部失敗しても読めるPDFを取り込む | apps/desktop/e2e/desktop-shell.e2e.spec.js | http://localhost:3000/?e2e=step1 | E2E | E2Eテスト一覧_STEP1優先.md | R-STEP1 | 作成済み |
| TC-E2E-011 | 検索ハイライト表示中にページ移動すると前ページのハイライトが残らない | apps/desktop/e2e/desktop-shell.e2e.spec.js | http://localhost:3000/?dev=split | E2E | テスト設計.md TD049 / ISS-030 NF-U5（page.tsx clearSearchHighlights） | R011 | 作成済み |

### 自動化判別の根拠

dev preview の挙動を Playwright で実機調査（ステッパー `data-testid=step-<id>` 全4ステップ確認、各ステップの UI 要素・ハイライト矩形・出力サンプル・pageerror 無しを確認）した結果、自動化可能なのは「dev preview で決定論的に再現できる UI 観点」に限られる。

- **TC-E2E-S1-001〜006 / TC-E2E-S1-011 を実装**: `?e2e=step1` では dev preview を無効化し、`window.__PDF_TOOL_E2E__` で Tauri dialog と sidecar 応答を差し替える。初期表示、ファイル選択呼び出し、正常取込、出力先設定後のSTEP2遷移、選択キャンセル、`pdf_info` 失敗、複数PDF選択時の一部失敗復旧を実DOMで判定する。
- **TC-E2E-011 を実装**: split ステップ（4ページ目）で検索ハイライト矩形（`.search-highlight-rect` / `.search-highlight-layer`）が描画されることを確認し、4ページ目以外の検索結果（8ページ目）をクリックして実際にページを移動（現在ページ表示 4→8）させ、移動後に前ページのハイライトが DOM に残らないことを判定した。`selectSearchResult → selectPageForPreview → clearSearchHighlights` は dev preview でも実コードパスで動作するため、期待結果「前ページのハイライトが残らない（NF-U5）」を直接判定できる。

## 5. 未実装テストケース

17 件（TC-E2E-001〜010, 012〜018）を `テスト成果物/未実装テストケース_E2E自動.md` に退避。STEP1優先の実機UI E2E（TC-E2E-S1-007〜010）は `E2Eテスト一覧_STEP1優先.md` で管理する。

退避の共通理由: dev preview は invoke を呼ばず静的サンプル状態を描画する設計で、多くの操作ハンドラが `devPreviewEnabled` で早期 return する。このため処理中状態の注入・sidecar 応答（部分失敗 / 欠落エラー / 旧応答到着）のモック・確認ダイアログ発火・リクエストゲート・再採番/affix の動的編集・ステップ遷移ガード（dev preview ではバイパスされる）が再現できない。これらは設計でも「invoke モック」前提であり、注入には製品コード変更（test seam 追加）が必要なため、本フェーズの「製品コード非変更」制約のもと自動化を見送った。

## 6. 実行結果

実行コマンド（cwd=apps/desktop）:

```
npm run test:e2e
```

結果:

```
Running 8 tests using 1 worker
8 passed (50.5s)
```

- TC-E2E-S1-001〜006、TC-E2E-S1-011、TC-E2E-011: **Pass**。
- webServer は既存 dev server（ポート3000）を再利用。常駐プロセスはテスト後に残さない設計（reuseExistingServer・本フェーズ終了時に手動起動分も停止）。

## 7. トレーサビリティ確認

- 実装テスト（TC-E2E-S1-001〜006、TC-E2E-S1-011、TC-E2E-011）: テスト関数タイトルに TC-ID を含み、近傍コメントに `TC / Risk` または `TC / TD / TV / TA / Risk / Spec` を保持。
- 退避テスト（17件）: `未実装テストケース_E2E自動.md` に元 TD/TV/TA/Risk・退避理由・必要対応・関連質問 ID（DQ03）付きで記載。
- E2E レーン 18 件（TC-E2E-001〜018）の内訳: 実装 1・退避 17。STEP1優先 11件の内訳: ブラウザE2E実装 7・実機UI E2E 4。欠落・取りこぼしなし。

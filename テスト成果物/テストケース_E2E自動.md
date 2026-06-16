# テストケース（E2E自動）

## 1. 作成対象

- 実行区分: E2E自動
- 対象TD: TD043, TD044, TD045, TD046, TD047b, TD048, TD049, TD050, TD056, TD068, TD069（計11TD）
- テストケースIDプレフィックス: TC-E2E-*

## 2. 参照資料

- テスト成果物/テスト設計.md（3.10節 E2Eレーン、TD043-TD050, TD056, TD068, TD069, TD047b）
- テスト成果物/テスト設計_質問票.md（DQ03）
- テスト成果物/テストケース_質問待ち.md（TC-E2E-001〜TC-E2E-018 を格納）

## 3. E2E自動テストで実行するテストケース

**Playwright 導入確定（@playwright/test 1.60.0・chromium 導入済み）。実行手段は STEP1 取込E2Eハーネス（`?e2e=step1`）と dev preview モード（`?dev=<stepId>`）を併用する。**

STEP1のPDF取込は、Tauriのファイル選択とsidecar応答をハーネスで差し替えて自動化した。dev preview の静的 early-return 設計で再現できない 17 件（処理中状態注入・旧応答破棄・部分失敗注入・確認ダイアログ発火・リクエストゲート・再採番/affix の動的編集・ステップ遷移ガード）は `未実装テストケース_E2E自動.md` に退避済み（DQ03 は導入確定だが invoke モック test seam が別途必要なため）。

| テストケースID | 元テスト設計ID | テスト観点ID | テストアプローチID | 実行区分 | テストレベル/タイプ | 優先度 | テストケース名 | 前提条件 | 入力/データ | 手順 | 期待結果 | 確認方法/証跡 | 関連質問ID | 仕様 | リスクID | 状態 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| TC-E2E-S1-001 | STEP1優先 | TV-S1 | TA-S1 | E2E自動 | E2E | 高 | STEP1初期表示でPDF未選択状態とPDF選択ボタンが表示されること | `?e2e=step1` で Tauri open / sidecar をハーネス化 | 初期状態 | 1. STEP1を開く 2. 未選択表示、PDF選択ボタン、次へボタン無効、ステータスを確認する | PDF未選択案内とPDF選択ボタンが表示され、STEP2へ進めない | Playwright実行ログ・DOM評価（apps/desktop/e2e/desktop-shell.e2e.spec.js） | DQ03（導入確定） | E2Eテスト一覧_STEP1優先.md | R-STEP1 | 作成済み |
| TC-E2E-S1-002 | STEP1優先 | TV-S1 | TA-S1 | E2E自動 | E2E | 高 | PDF選択操作でファイル選択処理が呼ばれること | `?e2e=step1` で Tauri open / sidecar をハーネス化 | ファイル選択キャンセル相当の空配列 | 1. STEP1を開く 2. PDF選択を実行する 3. open:pdf 呼び出しを確認する | ファイル選択処理が呼ばれ、キャンセル時に一覧は未選択のまま | Playwright実行ログ・DOM評価（apps/desktop/e2e/desktop-shell.e2e.spec.js） | DQ03（導入確定） | E2Eテスト一覧_STEP1優先.md | R-STEP1 | 作成済み |
| TC-E2E-S1-003 | STEP1優先 | TV-S1 | TA-S1 | E2E自動 | E2E | 高 | 有効なPDF選択後、PDF一覧・ページ数・プレビューが反映されること | `?e2e=step1` で Tauri open / sidecar をハーネス化 | 2ページPDF相当の `pdf_info` と `page_preview` 応答 | 1. STEP1を開く 2. PDF選択を実行する 3. 一覧、ページ数、プレビュー、呼び出し順を確認する | PDF名、2ページ、プレビューが表示され、`open:pdf`、`pdf_info`、`page_preview` が呼ばれる | Playwright実行ログ・DOM評価（apps/desktop/e2e/desktop-shell.e2e.spec.js） | DQ03（導入確定） | E2Eテスト一覧_STEP1優先.md | R-STEP1 | 作成済み |
| TC-E2E-S1-004 | STEP1優先 | TV-S1 | TA-S1 | E2E自動 | E2E | 高 | PDFと出力先設定後、STEP2へ進めること | `?e2e=step1` で Tauri open / sidecar をハーネス化 | PDFパス1件、出力先フォルダ1件 | 1. PDFを選択する 2. 出力先を選択する 3. 次へ進む | STEP2「仕分けルール」が表示される | Playwright実行ログ・DOM評価（apps/desktop/e2e/desktop-shell.e2e.spec.js） | DQ03（導入確定） | E2Eテスト一覧_STEP1優先.md | R-STEP1 | 作成済み |
| TC-E2E-S1-005 | STEP1優先 | TV-S1 | TA-S1 | E2E自動 | E2E | 高 | PDF選択キャンセル時、一覧とステータスが壊れないこと | `?e2e=step1` で Tauri open / sidecar をハーネス化 | 読込済みPDF1件、2回目のファイル選択キャンセル | 1. PDFを読み込む 2. もう一度PDF選択を実行してキャンセルする 3. 一覧、ページ数、ステータス、追加 `pdf_info` 不発を確認する | 読込済みPDFが維持され、キャンセルで不正な再読込やエラー表示にならない | Playwright実行ログ・DOM評価（apps/desktop/e2e/desktop-shell.e2e.spec.js） | DQ03（導入確定） | E2Eテスト一覧_STEP1優先.md | R-STEP1 | 作成済み |
| TC-E2E-S1-006 | STEP1優先 | TV-S1 | TA-S1 | E2E自動 | E2E | 高 | `pdf_info`失敗時、エラー表示となり一覧へ不正反映しないこと | `?e2e=step1` で Tauri open / sidecar をハーネス化 | `pdf_info` がエラー応答を返すPDF | 1. STEP1を開く 2. 壊れたPDF相当を選択する 3. エラー表示、一覧未反映、次へボタン無効を確認する | `PDF取込エラー` が表示され、対象PDFは一覧に追加されない | Playwright実行ログ・DOM評価（apps/desktop/e2e/desktop-shell.e2e.spec.js） | DQ03（導入確定） | E2Eテスト一覧_STEP1優先.md | R-STEP1 | 作成済み |
| TC-E2E-S1-011 | STEP1優先 | TV-S1 | TA-S1 | E2E自動 | E2E | 高 | 複数PDF選択時、1件失敗しても読めるPDFを取り込めること | `?e2e=step1` で Tauri open / sidecar をハーネス化 | 正常PDF2件、`pdf_info` 失敗PDF1件 | 1. STEP1を開く 2. 正常2件＋失敗1件を同時選択する 3. 一覧、警告ステータス、プレビュー呼び出しを確認する | 正常PDF2件は一覧に入り、失敗PDFは一覧に混入せず、警告に失敗件数と対象名が表示される | Playwright実行ログ・DOM評価（apps/desktop/e2e/desktop-shell.e2e.spec.js） | DQ03（導入確定） | E2Eテスト一覧_STEP1優先.md | R-STEP1 | 作成済み |
| TC-E2E-011 | TD049 | TV049 | TA009 | E2E自動 | E2E | 高 | 検索ハイライト表示中にページ移動→前ページのハイライトが残らないこと | dev preview（?dev=split）でハイライトが描画されている状態 | ハイライト表示中のページ移動操作 | 1. ?dev=split を開きハイライト矩形（svg rect/highlightクラス）の存在を確認する 2. 次ページへ移動する 3. ハイライトが DOM に残らないことを検証する | 前ページのハイライトがページ移動後に残留しない（svgRects=0・highlightクラス=0） | Playwright実行ログ・DOM評価（apps/desktop/e2e/desktop-shell.e2e.spec.js） | DQ03（導入確定） | テスト設計.md TD049 / ISS-030 NF-U5 / page.tsx clearSearchHighlights | R011 | 作成済み |

**測定手段の注記**: TC-E2E-S1-001 から TC-E2E-S1-006 は `window.__PDF_TOOL_E2E__` でファイル選択とsidecar応答を差し替える。TC-E2E-011 は設計記載の「invoke モック」ではなく dev preview を測定手段とする。page.tsx の `clearSearchHighlights` は dev preview のページ移動でも実行されるため、期待結果「前ページのハイライトが残らない（NF-U5）」を実 DOM で判定できる。残り 17 件は invoke モック注入口が無いと再現できず退避。

## 4. 上流成果物への追記・更新

STEP1取込不具合の切り分けを優先するため、`E2Eテスト一覧_STEP1優先.md` を追加した。E2Eレーンの既存TD全行は設計段階から状態=質問待ち（DQ03）として記録されている。

## 5. カバレッジ確認

| テスト設計ID | 対応テストケースID | 実行区分 | 状態 | 出力ファイル | カバー状況 |
|---|---|---|---|---|---|
| STEP1優先 | TC-E2E-S1-001〜TC-E2E-S1-006, TC-E2E-S1-011 | E2E自動 | 作成済み | テストケース_E2E自動.md / E2Eテスト一覧_STEP1優先.md | 実装済み（E2Eハーネス） |
| TD043 | TC-E2E-001 | E2E自動 | 質問待ち | テストケース_質問待ち.md | DQ03待ち |
| TD044 | TC-E2E-002 | E2E自動 | 質問待ち | テストケース_質問待ち.md | DQ03待ち |
| TD045 | TC-E2E-003, TC-E2E-004 | E2E自動 | 質問待ち | テストケース_質問待ち.md | DQ03待ち |
| TD046 | TC-E2E-005 | E2E自動 | 質問待ち | テストケース_質問待ち.md | DQ03待ち |
| TD047b | TC-E2E-006 | E2E自動 | 質問待ち | テストケース_質問待ち.md | DQ03待ち |
| TD048 | TC-E2E-007〜TC-E2E-010 | E2E自動 | 質問待ち | テストケース_質問待ち.md | DQ03待ち |
| TD049 | TC-E2E-011 | E2E自動 | 作成済み | テストケース_E2E自動.md | 実装済み（dev preview） |
| TD050 | TC-E2E-012, TC-E2E-013 | E2E自動 | 質問待ち | テストケース_質問待ち.md | DQ03待ち |
| TD056 | TC-E2E-014〜TC-E2E-016 | E2E自動 | 質問待ち | テストケース_質問待ち.md | DQ03待ち |
| TD068 | TC-E2E-017 | E2E自動 | 質問待ち | テストケース_質問待ち.md | DQ03待ち |
| TD069 | TC-E2E-018 | E2E自動 | 質問待ち | テストケース_質問待ち.md | DQ03待ち |

## 6. Case Expansion Ledger（ケース展開台帳）

| テスト設計ID | 期待TC数 | 実TC数 | 不足数 | 対応テストケースID | 分割方針 | 代表抽出理由 | 集約判定ルール | 状態 |
|---|---|---|---|---|---|---|---|---|
| TD043 | 1 | 1 | 0 | TC-E2E-001 | 質問待ち | — | — | 質問待ち |
| TD044 | 1 | 1 | 0 | TC-E2E-002 | 質問待ち | — | — | 質問待ち |
| TD045 | 2 | 2 | 0 | TC-E2E-003, TC-E2E-004 | 旧応答破棄+warning（編集種別代表2） | — | — | 質問待ち |
| TD046 | 1 | 1 | 0 | TC-E2E-005 | 質問待ち | — | — | 質問待ち |
| TD047b | 1 | 1 | 0 | TC-E2E-006 | 質問待ち | — | — | 質問待ち |
| TD048 | 4 | 4 | 0 | TC-E2E-007〜TC-E2E-010 | 全クリア/PDF除外/再採番/復元 | — | — | 質問待ち |
| TD049 | 1 | 1 | 0 | TC-E2E-011 | 質問待ち | — | — | 質問待ち |
| TD050 | 2 | 2 | 0 | TC-E2E-012, TC-E2E-013 | 未完了直行抑止/空状態提示 | — | — | 質問待ち |
| TD056 | 3 | 3 | 0 | TC-E2E-014〜TC-E2E-016 | search_text/index_candidates/blank_candidatesの切替 | — | — | 質問待ち |
| TD068 | 1 | 1 | 0 | TC-E2E-017 | 質問待ち | — | — | 質問待ち |
| TD069 | 1 | 1 | 0 | TC-E2E-018 | 質問待ち | — | — | 質問待ち |

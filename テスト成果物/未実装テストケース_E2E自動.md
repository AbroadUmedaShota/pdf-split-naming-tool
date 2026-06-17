# 未実装テストケース（E2E自動）

## 1. 対象

- 実行区分: E2E自動（TC-E2E-*）
- 対象アプリ: apps/desktop（Next.js）http://localhost:3000 の dev preview モード（`?dev=<stepId>`）
- 本ファイルは、Playwright 導入後も dev preview モードでは再現できず自動化を見送った E2E テストケースを退避する。

dev preview モード（app/page.tsx `shouldUseDevPreviewMode()`）は、Tauri/Python サイドカー無しで「サンプル状態の本番想定 UI」を**静的に**描画する仕組みである。多くの操作ハンドラは `devPreviewEnabled` で早期 return し、invoke を一切呼ばない。このため以下の動的振る舞いは dev preview では発生させられない:

- invoke 実行中の「処理中」状態（busy ガード）の注入
- sidecar 応答（部分失敗 summary、欠落エラー応答、旧応答到着）のモック注入
- 破壊的操作の確認ダイアログ（confirmAction）の発火（dev preview では対象操作が早期 return する）
- リクエストゲート・連打ガード・世代カウンタの動的検証
- 再採番・affix 追加削除の動的な状態遷移
- ステップ遷移ガード（`requestStepChange` は dev preview では `switchDevPreviewStep` を呼ぶだけでガードをバイパスする）

これらは設計（テスト設計.md TD043-050/047b/056/068/069）でも測定手段が「Playwright（invoke モック）／未導入時は手動」と定義されており、invoke モック注入の test seam が前提である。現状の dev preview には invoke モック注入口が無く、製品コードを変更しない限り注入できない。よって自動化せず退避する。

> 既存E2Eレーン（TC-E2E-001〜018）で実装済みは TC-E2E-011（検索ハイライトのページ移動後残留なし）の1件。STEP1優先の追加E2Eは TC-E2E-S1-001〜006、TC-E2E-S1-011、TC-E2E-S1-012、STEP2/STEP3操作系の追加E2Eは TC-E2E-B6、TC-E2E-B8 を `apps/desktop/e2e/desktop-shell.e2e.spec.js` に実装済み。dev preview のページ移動でも `clearSearchHighlights` が実行されるため、TC-E2E-011 の期待結果を実 DOM で判定できる。

## 2. 参照資料

| 資料名 | パス |
|---|---|
| テストケース_E2E自動 | テスト成果物/テストケース_E2E自動.md |
| テストケース_質問待ち | テスト成果物/テストケース_質問待ち.md（TC-E2E-001〜018） |
| テスト設計 | テスト成果物/テスト設計.md（3.10節 E2Eレーン） |
| テスト設計_質問票 | テスト成果物/テスト設計_質問票.md（DQ03） |
| 対象実装 | apps/desktop/app/page.tsx（dev preview 挙動・各操作ハンドラの早期 return） |

## 3. 未実装テストケース

| テストケースID | 元テスト設計ID | テスト観点ID | テストアプローチID | テストレベル/タイプ | 優先度 | テストケース名 | 未実装理由 | 実装に必要な確認・対応 | 関連質問ID | 仕様 | リスクID | 状態 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| TC-E2E-001 | TD043 | TV043 | TA009 | E2E | 高 | sidecar実行中に関連ボタンが無効化・処理中表示になること | 自動化困難: dev preview は invoke を呼ばず処理中（busy）状態を注入できない | invoke モック注入の test seam（製品コード側）または実機 Tauri 環境での手動確認 | DQ03 | ISS-001、page.tsx busy、SSI012 | R006/R007 | 未実装 |
| TC-E2E-002 | TD044 | TV044 | TA009 | E2E | 高 | export完了後の再出力抑止（canExport=false・preflightクリア） | 自動化困難: dev preview は export 後の動的状態遷移を再現できない（export 結果は固定サンプル） | invoke モック注入または実機での手動確認 | DQ03 | ISS-001、page.tsx | R006 | 未実装 |
| TC-E2E-003 | TD045 | TV045 | TA009 | E2E | 高 | 応答待ち中に分割点変更→旧応答破棄・警告表示 | 自動化困難: dev preview は応答待ち→旧応答到着の世代カウンタ経路を再現できない | invoke モック（遅延応答）注入が必要 | DQ03 | ISS-024、page.tsx 世代カウンタ | R006/R007 | 未実装 |
| TC-E2E-004 | TD045 | TV045 | TA009 | E2E | 高 | 応答待ち中にメタデータ入力→旧応答破棄・警告表示 | 自動化困難: 同上（旧応答到着の再現不可） | invoke モック（遅延応答）注入が必要 | DQ03 | ISS-024、page.tsx 世代カウンタ | R006/R007 | 未実装 |
| TC-E2E-005 | TD046 | TV046 | TA009 | E2E | 高 | 部分失敗summary→attention表示・失敗ファイル列挙・緑バッジ非表示 | 自動化困難: dev preview の export summary は created=3/failed=0 固定で部分失敗を注入できない | 部分失敗 summary をモック応答で返す test seam が必要 | DQ03 | ISS-008、page.tsx stepState | R006 | 未実装 |
| TC-E2E-006 | TD047b | TV047 | TA009 | E2E | 高 | summary/checks欠落エラー応答→フロント型ガードが弾きクラッシュなし | 自動化困難: dev preview では欠落エラー応答を注入できず、型ガードの入力前提を作れない | 欠落エラー応答をモックで返す test seam が必要（正常系レンダリングへ意味をすり替えない） | DQ03 | ISS-025、page.tsx runPreflight/runExport ガード、SSI019 | R006 | 未実装 |
| TC-E2E-007 | TD048 | TV048 | TA009 | E2E | 中 | 全クリア操作→確認ダイアログ表示 | 自動化困難: dev preview では全クリア等の破壊的操作ハンドラが早期 return し confirmAction が発火しない | confirmAction を発火させる経路（非 dev preview の test seam）または実機手動確認 | DQ03 | ISS-009/010、page.tsx | R004 | 未実装 |
| TC-E2E-008 | TD048 | TV048 | TA009 | E2E | 中 | PDF除外操作→確認ダイアログ表示 | 自動化困難: 同上（確認ダイアログ非発火） | 同上 | DQ03 | ISS-009/010、page.tsx | R004 | 未実装 |
| TC-E2E-009 | TD048 | TV048 | TA009 | E2E | 中 | 再採番操作→確認ダイアログ表示 | 自動化困難: 同上（確認ダイアログ非発火） | 同上 | DQ03 | ISS-009/010、page.tsx | R004 | 未実装 |
| TC-E2E-010 | TD048 | TV048 | TA009 | E2E | 中 | 作業中データあり状態で復元→確認ダイアログ表示 | 自動化困難: 同上（確認ダイアログ非発火） | 同上 | DQ03 | ISS-009/010、page.tsx | R004 | 未実装 |
| TC-E2E-012 | TD050 | TV050 | TA009 | E2E | 中 | 未完了STEP2へのSTEP3からの直行抑止 | 自動化困難: dev preview の `requestStepChange` はガードをバイパスして `switchDevPreviewStep` を呼ぶため遷移抑止が再現されない | 非 dev preview のステップガード経路を駆動できる test seam または実機手動確認 | DQ03 | ISS-015、要件6、SSI002 | R014 | 未実装 |
| TC-E2E-013 | TD050 | TV050 | TA009 | E2E | 中 | 空状態で次ステップ試行→不足項目提示 | 自動化困難: dev preview は常にサンプル充足状態で初期化され、空状態を作れない | 空状態を初期化できる test seam または実機手動確認 | DQ03 | ISS-015、要件6、SSI002 | R014 | 未実装 |
| TC-E2E-014 | TD056 | TV056 | TA010 | E2E | 中 | search_text実行中のリクエストゲート・連打ガード・PDF切替後旧結果非残留 | 自動化困難: dev preview は search_text の invoke を呼ばず（早期 return）、実行中状態・連打ゲートを再現できない | invoke モック（実行中保持）注入が必要 | DQ03 | page.tsx リクエストゲート | R010/R011 | 未実装 |
| TC-E2E-015 | TD056 | TV056 | TA010 | E2E | 中 | index_candidates実行中のリクエストゲート・連打ガード・PDF切替後旧結果非残留 | 自動化困難: 同上（invoke 非発火） | invoke モック注入が必要 | DQ03 | page.tsx リクエストゲート | R010/R011 | 未実装 |
| TC-E2E-016 | TD056 | TV056 | TA010 | E2E | 中 | blank_candidates実行中のリクエストゲート・連打ガード・PDF切替後旧結果非残留 | 自動化困難: 同上（invoke 非発火） | invoke モック注入が必要 | DQ03 | page.tsx リクエストゲート | R010/R011 | 未実装 |
| TC-E2E-017 | TD068 | TV068 | TA009 | E2E | 中 | 連番入力→空欄化→再採番で連番が再び埋まる（手動固定にならない） | 自動化困難: dev preview は採番入力・再採番ハンドラの動的編集を反映しない（サンプル状態固定） | 非 dev preview の入力編集経路を駆動できる test seam または実機手動確認 | DQ03 | ISS-030 NF-U16、page.tsx | R012 | 未実装 |
| TC-E2E-018 | TD069 | TV069 | TA009 | E2E | 中 | affix追加→削除→再追加で旧値が全セグメントに復活しない | 自動化困難: dev preview は affix 編集の動的状態遷移を再現しない（サンプル状態固定） | 非 dev preview の affix 編集経路を駆動できる test seam または実機手動確認 | DQ03 | page.tsx affix 復元抑止 | R012 | 未実装 |

## 4. 実装に必要な確認・対応

1. **invoke モック注入口の整備（最大の前提）**: TD043/044/045/046/047b/056 系（処理中・旧応答破棄・部分失敗・欠落応答・リクエストゲート）は、Playwright から sidecar 応答を差し替えられる test seam が必要。dev preview は invoke を呼ばない設計のため、別途「invoke をモックする dev フラグ」や `window.__E2E_INVOKE_MOCK__` 相当の注入口を製品側に用意する判断（製品コード変更を伴う）が要る。本フェーズの制約「製品コードを変更しない」に抵触するため未実装。
2. **確認ダイアログ経路（TD048）**: dev preview ではなく invoke モックで実 UI フローを動かす必要がある。確認ダイアログ自体は Playwright の `page.on('dialog')`（window.confirm）または Tauri confirm のフックで検証できるが、発火させる前段の操作が dev preview で早期 return する。
3. **ステップガード・空状態（TD050）**: dev preview がガードをバイパスするため、非 dev preview かつサンプル状態を空にできる初期化経路が要る。
4. **採番・affix 編集（TD068/069）**: 動的編集を反映する非 dev preview 経路が要る。
5. 上記いずれも DQ03（Playwright 導入＝確定済み）に加えて「invoke モック test seam の追加可否」というより踏み込んだ判断が前提になる。製品コード変更可否を PM/建設部で確認後に再分類する。

## 5. トレーサビリティ確認

- 退避 17 件（TC-E2E-001〜010, 012〜018）はすべて元テスト設計 ID（TD043-050/047b/056/068/069）・TV・TA・Risk を保持。
- 実装 1 件（TC-E2E-011 / TD049 / TV049 / TA009 / R011）、STEP1優先 8 件（TC-E2E-S1-001〜006, TC-E2E-S1-011, TC-E2E-S1-012）、STEP2/STEP3操作系 2 件（TC-E2E-B6, TC-E2E-B8）は `apps/desktop/e2e/desktop-shell.e2e.spec.js` に実装し、トレースコメントを保持。
- E2E レーンの元 18 件（TC-E2E-001〜018）の内訳: 実装 1・退避 17。STEP1優先/追加のブラウザE2E 11件、実機E2E系 8件、STEP2/STEP3操作系 2件を現行資料に反映済み。欠落なし。

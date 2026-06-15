# run-test-process 進行状況

## 完了フェーズ

- フェーズ1: テスト計画（create-test-plan → review-test-plan）— 完了（セッション内）
- フェーズ2: テスト分析（create-test-analysis → review-test-analysis）— 完了（セッション内）
- フェーズ3: テスト設計（create-test-design → review-test-design）— 完了（セッション内）
- フェーズ4: テストケース＋実装エントリーゲート（create-test-cases → review-test-cases → review-test-artifacts → ゲート判定）— 完了（セッション内）
- フェーズ5: コードベース自動化（create-test-code → review-test-code → execute-codebase-tests）— 完了（セッション内）
- フェーズ6: E2E自動化（create/execute/review-playwright-e2e）— スキップ（Playwright 未導入・DQ03 未確定）。E2Eは「設計済み・未実装」として最終レポートに可視化。
- フェーズ7: 最終レポート（create-test-report → review-test-report）— 完了（セッション内）

### フェーズ7（最終レポート）

成果物:

- 最終レポートフォルダ: `テスト成果物/report/20260615172745_report/`（index.html・md/・html/・raw/manifest.json）
- `テスト成果物/テストレポートレビュー結果.md`（review-test-report・残 P0/P1/P2 なし）

create-test-report:

- 採用実行フォルダ: `20260615172019_コードベーステスト`（E2E実行フォルダは未検出＝未実装で正）。
- サマリ: Total 213 / Executed 144 / Pass 142 / Fail 2 / N/A 1 / NotRun 0 / 質問待ち 68 / 未実装 30 / Pass率 98.6%。網羅性: 期待207・実208・不足0（Ledger103行）。
- index.html に手動追記2点（凍結出力への補足・元成果物/実行フォルダ不変）: (1)「バグの現状（実行後フォローアップ）」＝BUG-001修正済み（pytest 384/0 緑）/BUG-002環境起因未解消を区別。(2)「9. リリース可否の総括」＝レーン別状態とNoGo所見。

review-test-report:

- 件数を独立再計算し全項目一致（Pass率分母正・N/A除外）。ローカルhref50件すべて解決。機密露出なし。各レビュー結果は残P0/P1/P2なしを内部明記。
- 第1パスで鮮度ギャップ（BUG-001修正後の未反映＝P2相当）を index.html 追記で解消。第2パスで残 P0/P1/P2 なしを確認。
- 残 P3: 未実装一覧の本文参照ID（TC-CB-001/135/144）は一次テーブル行ではなく説明参照（件数誤りではない・修正不要）。DQ01-11 未確定は質問票HTMLで可視化済み。

リリース可否の総括: 現状 NoGo（出荷判定保留）。製品起因の出荷阻害バグ（P0）は未確認だが、E2E自動18件が未実装、手動受入44件が未実施でカバレッジ未充足。出荷前必須: 手動受入の実施体制（DQ04/05）＋R001プレビュー描画修正の実機最終確認（ともにP1）。BUG-002環境整備・E2E導入判断（DQ03）はP2。

## 生成ファイル

- `テスト成果物/テスト計画書.md`（create-test-plan で作成）
- `テスト成果物/テスト計画レビュー結果.md`（review-test-plan で作成）
- `テスト成果物/テスト分析.md`（create-test-analysis で作成。SSI001-020・TV001-075・三パス）
- `テスト成果物/テスト分析_質問票.md`（Q1-Q11）
- `テスト成果物/テスト分析レビュー結果.md`（review-test-analysis で作成）
- `テスト成果物/テスト設計.md`（create-test-design で作成。TD001-075＋TD047a/047b・実行レーン①②③・Expected Case Yield）
- `テスト成果物/テスト設計_質問票.md`（DQ01-DQ11）
- `テスト成果物/テスト設計レビュー結果.md`（review-test-design で作成）
- `テスト成果物/テストケース_コードベース.md`（create-test-cases。TC-CB-001〜145・確定レーン①）
- `テスト成果物/テストケース_E2E自動.md`（構造＋退避明記・全行質問待ち）
- `テスト成果物/テストケース_人間実行.md`（構造＋退避明記・全行質問待ち）
- `テスト成果物/テストケース_人間実行.csv`（ヘッダのみ・人間実行確定行ゼロ）
- `テスト成果物/テストケース_質問待ち.md`（TC-CB-146〜151・TC-E2E-001〜018・TC-MAN-001〜044＝68件）
- `テスト成果物/テストケースレビュー結果.md`（review-test-cases）
- `テスト成果物/テスト成果物横断レビュー結果.md`（review-test-artifacts）
- `テスト成果物/run-test-process_進行状況.md`（本ファイル）
- `テスト成果物/run-test-process_引き継ぎ.md`

## レビュー / ゲート結果

### フェーズ1（テスト計画）

- 残 P0/P1: なし。残 P2: 未決事項 Q1-Q8（計画第11節に集約）。残 P3: MD060 lint 警告・Rust本数確定。

### フェーズ2（テスト分析）

- 残 P0: なし
- 残 P1: なし
- 残 P2: なし（第1パスで UC3/UC6/UC7 のトレース欠落を P2 指摘→TV073-075 追加で解消、第2パスで残ゼロ確認）
- 残 P3: あり（質問票 Q1-Q11 の未確定＝サインオフ/性能基準・cargo環境/本数・Playwright導入・実機受入体制・テストデータ・OPEN課題ISS-027/028・updater旧版配布物・DEFERREDスコープ・stale復活のセッション内仕様 Q9・白紙閾値境界 Q10・分割マーカーHTML構造 Q11。参照資料に根拠がないためユーザー/PM確認待ち。Rust本数は cargo 実行時に確定）
- review-test-analysis の停止条件（P0/P1/P2 ゼロ）を満たして停止。修正→再レビューは2パス実施。
- 事実差異の記録: Rust 単体テスト `#[test]` 定義は lib.rs コード確認で27件（計画/ISS-014記載の13件と乖離）。cargo 未実行のため確定は質問票 Q2 で要確認。

### フェーズ3（テスト設計）

- 残 P0: なし
- 残 P1: なし
- 残 P2: なし（第1パスで TD003 の期待TC数 3→4＝型不正4区分の独立判定を P2 指摘→修正で解消、第2パスで残ゼロ確認）
- 残 P3: あり（DQ01-DQ11 の未確定＝分析 Q1-Q11 を1対1引き継ぎ。MD060 lint 警告は内容影響なしの体裁）
- review-test-design の停止条件（P0/P1/P2 ゼロ）を満たして停止。修正→再レビューは1パス（TD003）実施。
- 構造判断: TV047（エラー応答ガード）を実行レーン違いから TD047a（sidecar 契約・①）＋TD047b（フロント型ガード・②）へ分割（観点追加ではなく実施方法分離・上流不変）。
- 実行レーン振り分け確定: ①コードベース（pytest/check-*.mjs/cargo）= 確定 `設計済み` 約144 TC。②E2E（Playwright invoke モック）= 11行すべて `質問待ち`（DQ03 導入未確定・未導入時は手動退避）。③手動受入 = 実 PDF/実機/updater/幅/スキャンPDF を `質問待ち`（DQ04/05 体制・データ未確定、未実施を緑化しない判定観点付与）。

### フェーズ4（テストケース＋実装エントリーゲート）

- 残 P0: なし / 残 P1: なし / 残 P2: なし
- create-test-cases: 設計 TD001-075＋047a/047b を TC-* へ展開。確定レーン① TC-CB-001〜145、質問待ち68件（TC-CB-146〜151・TC-E2E-001〜018・TC-MAN-001〜044）。レーン別5ファイル＋CSV を生成。上流更新なし。
- review-test-cases: 第1パスで P1（TC-CB-049 入力セルの未エスケープ `\|` でテーブル破壊）・P2（E2E自動.md/人間実行.md の TC-ID範囲誤記、人間実行.md の不要 DQ08 参照）を指摘→修正。第2パスで全 TC 行＝17列（node検査）・残 P0/P1/P2 ゼロを確認。
- review-test-artifacts: R→TA→TV→TD→TC の全段連結を機械確認（TA15/TV75/TD76 すべて TC 到達・欠落なし）。3数量成果物（SSI・Expected Case Yield・Case Expansion Ledger）存在・突合一致。残 P0/P1 なし。
- 残 P3: あり（DQ01-DQ11 未確定／TC-MAN-026 の「その他残項目」集約は DQ04 確定時に細分化／MD060 lint）。

#### 実装エントリーゲート判定

- **確定レーン①（TC-CB-001〜145）は実装着手可。** pytest（recovery/tests/）・node（check-*.mjs）で展開。
- 総期待TC数: 確定レーン①143＋質問待ち仮置き。総実TC数: 213（確定145＋質問待ち68）。不足数0（TD037 のみ遷移境界で+1独立展開・理由記載）。質問待ち件数: 68。
- 質問待ち68件（コードベース6・E2E18・人間44）は該当 DQ 回答までブロック。DQ03（Playwright導入）は E2E 一括移送の前提。手動は DQ04/05 体制・実データ確定が前提（未実施を緑化しない）。

### フェーズ5（コードベース自動化）

成果物:

- `テスト成果物/テストコード実装結果.md`（create-test-code）
- `テスト成果物/未実装テストケース_コードベース.md`（区分A 24件＝node/ps1/全スイート・区分B 6件＝質問待ち TC-CB-146〜151）
- `テスト成果物/テストコードレビュー結果.md`（review-test-code・残 P0/P1/P2 なし）
- `recovery/tests/test_tc_cb_codebase.py`（新規 pytest 121関数。製品コード変更なし）
- 実行レポート: `テスト成果物/report/20260615172019_コードベーステスト/`（実行済み Markdown/CSV・生ログ・`コードベース_発見issue一覧.md`）

create-test-code:

- TC-CB-001〜145 のうち pytest 実装可能な **121件** を `test_tc_cb_codebase.py` に新規実装（全関数名に TC-CB-ID＋docstring に TC/TD/TV/TA/Risk）。
- 区分A **24件**（TC-CB-060, 106〜124, 134〜137）は既存 node check-*.mjs／全 pytest スイート／verify.ps1・sample-pdf-smoke.ps1 でカバー。新規 pytest は作らず未実装一覧へ退避（重複回避）。
- 区分B **6件**（TC-CB-146〜151・DQ02/08/09/10）は質問待ちで実装せず退避。
- 既存資産の利用: 実 public API（handle_request / build_yoshida_filename_preview / normalize_state_payload / StateManager / PdfService.search_text・blank_candidates）を直接駆動。コピーロジック検証なし。venv に pytest 9.1.0 を導入（pyproject の test extra・宣言済み資産の有効化。新規製品依存なし）。

review-test-code:

- 第1パスで P2×2（TC-CB-132 のアサーション弱／TC-CB-095 のラベル不一致）を指摘→修正。第2パスで残 **P0/P1/P2 なし**。P3×1（中段 import の体裁）は影響なしで未修整。

execute-codebase-tests（実行結果サマリ・TC-CB-001〜145＝145件）:

- **Pass 142 / Fail 2 / N/A 1**。
  - Pass 142 = pytest 新規121＋node 検査20＋check-all（TC-CB-135）1。
  - Fail 2 = BUG-001（TC-CB-134）・BUG-002（TC-CB-136）。**いずれも製品の実バグではない**。
    - BUG-001（P1）: 既存 `test_desktop_shell_contract.py::test_desktop_tauri_exposes_python_sidecar_bridge` が旧文字列 `generate_handler![run_sidecar]` を完全一致でアサート。製品 lib.rs は `generate_handler![run_sidecar, reveal_path]` へ拡張済み＝**テスト期待値の陳腐化**（製品変更不要・既存テスト更新が別途必要）。
    - BUG-002（P1）: `verify.ps1` がグローバル `python` を呼ぶがデプス未整備で exit 1＝**環境起因**。
  - N/A 1 = TC-CB-137（sample-pdf-smoke.ps1 が必須 `-PdfPath` を要求・サンプル PDF 未提供）。
- 参考（表外）: TC-CB-151（質問待ち・cargo）試行 = 22 passed / 5 failed。5失敗は `py` ランチャ不在の**環境起因**（既知事象）。DQ02 確定後に正式判定。
- 発見 BUG 件数: **2件**（BUG-001/002・ともに非製品バグ＝テスト陳腐化／環境）。
- 既存スイート全体ベースライン: `pytest recovery/tests/ -q` → 382 passed, 1 failed（上記 BUG-001 のみ）。

## 次フェーズ（フェーズ5: コードベース自動化＝create-test-code）の入力

- `テスト成果物/テストケース_コードベース.md`（TC-CB-001〜145・状態=作成済み・実施方法に pytest/node コマンド明記）
- `テスト成果物/テストケース_質問待ち.md`（TC-CB-146〜151 は DQ確定までブロック）
- `テスト成果物/テストケースレビュー結果.md` / `テスト成果物/テスト成果物横断レビュー結果.md`（残 P0/P1/P2 なし）
- 既存資産（重複回避の追加先）: pytest 19ファイル（recovery/tests/）・check-*.mjs 8ファイル（apps/desktop/scripts/）
- トレース維持: 実装テストに TC-CB-ID を残し TC→TD→TV→TA/R を追跡可能にする。

## 注意 / 既知の制約（計画に織り込み済み）

- E2E は現状ゼロ。Playwright は Tauri invoke モック範囲（UI/状態/ナビ）に限定。
- sidecar 実体を伴う検証（実PDFプレビュー/分割/出力・実機Tauri・updater）は人間実行（手動受入）。
- 中核経路バグ「プレビューが全く表示されない（PNG/JPEG不一致）」を R001（リスク度20・最高位）に反映。

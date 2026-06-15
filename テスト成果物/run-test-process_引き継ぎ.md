# run-test-process 引き継ぎ（全フェーズ完了・残作業の申し送り）

## run-test-process 完了状態（フェーズ7まで）

- フェーズ1〜5・7 完了。フェーズ6（E2E自動化）は Playwright 未導入・DQ03未確定でスキップ（設計済み・未実装として最終レポートに可視化）。
- 最終レポート: `テスト成果物/report/20260615172745_report/index.html`。レビュー結果: `テスト成果物/テストレポートレビュー結果.md`（残P0/P1/P2なし）。
- 自動レーン現状: コードベース Pass 142 / Fail 2 / N/A 1。**BUG-001（TC-CB-134）は修正済み**（`test_desktop_shell_contract.py` を前方一致化）→ `pytest tests/`（cwd=recovery）は 384 passed / 0 failed（緑）。残Failは BUG-002（verify.ps1 のグローバルpython依存＝環境起因・非製品）のみ。
- リリース可否: **NoGo（出荷判定保留）**。P0未確認だが、E2E自動18件未実装・手動受入44件未実施でカバレッジ未充足。
- 出荷前に潰すべき残作業:
  - P1: 手動受入44件の実施（実PDF・実機Tauri・updater）。前提＝DQ04（受入体制）・DQ05（テストデータ）の確定。
  - P1: 最高リスク R001（プレビュー描画・PNG/JPEG不一致）の修正は完了済み。実機での最終確認は手動受入レーンで要実施。
  - P2: DQ03（Playwright導入可否）確定 → E2E18件の実装 or 手動退避。
  - P2: BUG-002（verify.ps1 の interpreter 固定 or 依存整備）。製品変更不要。
- 残課題の根拠は質問票 DQ01-DQ11 と各レビュー結果に紐づく。製品コード・実行証跡フォルダは本フェーズで未改変。

---

## 旧フェーズ6（E2E自動化）への申し送り（参考・着手時に再利用）

E2E自動テスト実装（create-playwright-e2e-tests）が必要とする事実だけを記載する。

## 最重要: E2Eレーンは現状 DQ03 ブロックで実装不可

- E2E自動テストケース `テスト成果物/テストケース_E2E自動.md` は **構造のみ・全行退避済み**。実行可能行ゼロ。
- TC-E2E-001〜018（計18件）は `テスト成果物/テストケース_質問待ち.md` に格納され、状態＝質問待ち。**DQ03（Playwright 導入有無・設定所在）が未確定**のため実装着手不可。
- 現状確認: `apps/desktop/package.json` に Playwright 依存なし（grep で不在を確認）。Playwright 未導入。
- DQ03 の分岐:
  - 導入確定 → 質問待ちの TC-E2E-* を「作成済み」に更新し `テストケース_E2E自動.md` へ移送 → Tauri invoke モック範囲（UI/状態/ナビ）で Playwright 実装。
  - 未導入確定 → 同等観点を人間実行（探索的UI確認）として `テストケース_人間実行.md` へ移送（自動化しない）。
- 対象TD（DQ03確定時）: TD043〜050, TD047b, TD056, TD068, TD069（計11TD）。
- **依存の新規インストールはユーザー/PM 承認が前提**（Playwright 導入＝新規依存）。承認なしに着手しない。

## フェーズ5（コードベース自動化）完了状態

- 実装テスト: `recovery/tests/test_tc_cb_codebase.py`（pytest 121関数・全 PASS・製品コード変更なし）。
- 実行レポート: `テスト成果物/report/20260615172019_コードベーステスト/`（実行済み Markdown/CSV・生ログ・`コードベース_発見issue一覧.md`）。
- コードベース実行サマリ（TC-CB-001〜145＝145件）: **Pass 142 / Fail 2 / N/A 1**。
- 発見 BUG **2件**（ともに非製品バグ）:
  - BUG-001 / TC-CB-134（P1）: 既存 Rust 契約テスト `test_desktop_tauri_exposes_python_sidecar_bridge` の期待文字列が陳腐化（製品は `generate_handler![run_sidecar, reveal_path]` に拡張済み）。既存テストの更新が別途必要。
  - BUG-002 / TC-CB-136（P1）: `verify.ps1` がグローバル `python`（依存未整備）を呼び exit 1＝環境起因。
- N/A 1件: TC-CB-137（sample-pdf-smoke.ps1 が必須 `-PdfPath` 要求・サンプル PDF 未提供）。
- 質問待ち（区分B・実装ブロック中）: TC-CB-146〜151（DQ02 cargo/DQ08-09 segment/DQ10 白紙閾値）。`未実装テストケース_コードベース.md` 参照。

## 環境メモ（E2E/再実行で再利用）

- pytest: `recovery/.venv/Scripts/python.exe -m pytest`（本フェーズで venv に pytest 9.1.0 を導入。pyproject の test extra）。PyMuPDF 導入済み。
- node 検査: `node apps/desktop/scripts/check-all.mjs`（6検査）＋ `check-step-render.mjs`/`check-step-layout.mjs` 個別。全 PASS。
- Rust: `& "C:\Users\user\.cargo\bin\cargo.exe" test --manifest-path apps\desktop\src-tauri\Cargo.toml` → 22 passed / 5 failed（5失敗は `py` ランチャ不在の環境起因・既知事象。製品バグではない）。
- verify.ps1 / sample-pdf-smoke.ps1 は実機 sidecar/実 PDF 前提（手動受入レーン寄り）。

## レビュー状態

- `テスト成果物/テストコードレビュー結果.md`: 残 P0/P1/P2 なし（TC-CB-132 アサーション強化・TC-CB-095 ラベル是正を修正済み）。残 P3×1（中段 import の体裁・影響なし）。
- トレーサビリティ: pytest 全121関数が TC-CB-ID＋TD/TV/TA/Risk を保持。区分A/B は `未実装テストケース_コードベース.md` に元 ID 付きで退避。

## 次フェーズ（フェーズ6: E2E自動化＝create-playwright-e2e-tests）の入力

- `テスト成果物/テストケース_E2E自動.md`（構造のみ・全行退避）／`テスト成果物/テストケース_質問待ち.md`（TC-E2E-001〜018）
- `テスト成果物/テスト設計.md`（3.10節 E2Eレーン・TD043-050/047b/056/068/069）／`テスト成果物/テスト設計_質問票.md`（DQ03）
- **DQ03 の回答が着手の前提**。未回答なら E2E 自動化はスキップし、未実装/質問待ちとして可視化したまま最終レポート（create-test-report）へ進む判断もあり得る。

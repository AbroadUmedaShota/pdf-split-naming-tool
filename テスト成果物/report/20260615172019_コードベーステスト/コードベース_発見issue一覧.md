# コードベース_発見issue一覧

| Bug ID | 要約 | 優先度 | 何がどうなったか | 期待結果 | トレーサビリティ | 発見日時 | 関連実行済みテストケース |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BUG-001 | TC-CB-134 pytest 19ファイル全件が存在し全件パスする がFail | P1 | TC-CB-134 がテスト実行でFailになった。詳細は実行ログを参照。 | 19ファイル全件の test_* 関数がエラーなく PASSED になり、FAILED が0件 | TC-CB-134 / 元テスト設計ID: TD057 / テスト観点ID: TV057 / テストアプローチID: TA011 / 仕様: docs/05検証コマンド、SSI017 / リスクID: R001,R003,R004,R014 | 20260615172019 | テスト成果物\report\20260615172019_コードベーステスト\20260615172019_テストケース_コードベース_実行済み.md |
| BUG-002 | TC-CB-136 verify.ps1 が存在し実行できる がFail | P1 | TC-CB-136 がテスト実行でFailになった。詳細は実行ログを参照。 | verify.ps1 が最後まで実行され、異常終了しない | TC-CB-136 / 元テスト設計ID: TD057 / テスト観点ID: TV057 / テストアプローチID: TA011 / 仕様: docs/05検証コマンド、scripts/verify.ps1、SSI017 / リスクID: R001,R003,R004,R014 | 20260615172019 | テスト成果物\report\20260615172019_コードベーステスト\20260615172019_テストケース_コードベース_実行済み.md |

## 原因区分の補足（環境 vs 実バグ）

失敗・N/A の原因を「製品コードの実バグ」と「テスト/環境起因」に切り分けて記録する。いずれも本フェーズで追加した新規テストの失敗ではない。

| ID | 区分 | 根本原因 | 是正の所在 |
|---|---|---|---|
| BUG-001 / TC-CB-134 | テスト陳腐化（実バグではない） | 既存 `recovery/tests/test_desktop_shell_contract.py::test_desktop_tauri_exposes_python_sidecar_bridge` が旧文字列 `tauri::generate_handler![run_sidecar]` を完全一致でアサート。製品 lib.rs は `generate_handler![run_sidecar, reveal_path]` へ拡張済み（`reveal_path` コマンド追加）で、テスト側の期待値が未更新。製品の機能後退ではなく、テストの期待値固定化が古い。製品コードは本フェーズ対象外のため未修整（既存テストの更新は別途必要）。 | 既存テストの期待値更新（製品変更不要） |
| BUG-002 / TC-CB-136 | 環境起因（実バグではない） | `scripts/verify.ps1` がグローバルの `python`（PATH 上）を呼ぶ設計だが、当環境のグローバル python に pytest/PyMuPDF が無く exit 1。テスト資産は recovery/.venv に導入済み。スクリプト自体の論理は正常で、前提とする実行環境（依存入りの python on PATH）が未整備。 | 実行環境整備 or verify.ps1 の interpreter 指定（製品変更不要） |
| TC-CB-137（N/A） | 実行不能（入力未提供） | `scripts/sample-pdf-smoke.ps1` は必須引数 `-PdfPath` を要求するが、リポジトリにサンプル PDF フィクスチャが無いため未起動。テスト設計上は実 PDF を伴う手動受入スコープ。 | 実 PDF 提供時に実行（手動レーン） |

## 参考: コードベース表外の観測（TC-CB-151 質問待ち・cargo）

TC-CB-151（質問待ち DQ02）は本コードベース表に含まれないが、指示により cargo を試行した結果を残す。

- 実行: `cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml` → **22 passed / 5 failed**。
- 5 失敗は `tests::resident_sidecar_*` 系で、`std::process::Command::new("py")`（Python ランチャ `py -3.12`）が当環境に不在（`program not found`）なため。**環境起因であり製品コードの実バグではない**（reveal_target 等の本体ロジックテストは成功）。
- DQ02（実行環境・対象本数の確定）回答後に正式判定する。

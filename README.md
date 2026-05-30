# PDF分割命名ツール

## 目的

過去に開発していた `PDF分割命名ツール_v3_1_1` の元ソース消失に備え、ビルド済み配布物から仕様と実装構造を復元し、社内展開可能なデスクトップアプリとして再構築するための作業場所です。

## 状態

- 作成日: 2026-05-19
- 現在の段階: Tauri/Next.js のデスクトップアプリ本体と、Python sidecar のPDF処理部品へ整理済み。現段階の仕様は最小構成
- 元ソース: 主要なローカル開発置き場では未発見
- ビルド済み配布物: `\\ao100\103_共有\アプリケーション\自社開発シリーズ\PDF分割命名ツール_v3_1_1`
- 解析済み入口モジュール: `pdf_splitter_app.py`
- 旧配布候補: `recovery/dist/pdf-split-naming-tool-recovery-20260521-ocrfix-rollout.zip`
- 現在のユーザー向けアプリ: `apps/desktop/`
- 現在のPDF処理部品: `recovery/pdf_splitter_tool/`
- 現段階の優先仕様: `docs/2026-05-30_最小構成仕様.md`
- OCR方針: 最小構成では後回し。将来有効化する場合もOCRエンジンは同梱せず、事前OCR済みPDFまたは既存テキスト層ありPDFを入力条件にする

## 現在の実装構成

ユーザーが起動して操作するアプリは `apps/desktop/` の1つです。

`recovery/pdf_splitter_tool/` は、Tauriアプリから呼び出すPython sidecarです。PDFページ数取得、プレビュー生成、分割、命名、出力前チェック、状態保存を担当します。旧Tkinter GUIは現段階の実装対象から外しており、独立した2つ目のユーザー向けアプリとしては扱いません。

## フォルダ

- `docs/`: 調査結果、仕様書、画面別機能仕様、社内展開メモ、配布前チェックリスト
- `docs/assets/`: 仕様書で参照する画像などの管理対象アセット
- `apps/desktop/`: Tauri + Next.js のデスクトップアプリ本体
- `recovery/`: Python sidecar、PDF処理ロジック、テスト。ユーザー向けGUIアプリではない
- `artifacts/analysis/`: 配布物から抽出した解析用ファイル。Git管理対象外
- `recovery/dist/`: 旧PyInstaller配布候補。Git管理対象外

## 次に決めること

1. 現場PDFで、PDF取込、手動分割、1ページ分割、命名、出力が成立するか確認する。
2. Tauriアプリとしての配布方法を確定する。
3. `recovery/` のフォルダ名を将来 `sidecar/` または `backend/` へ変更するか判断する。
4. OCR、白紙検出、プリセット管理、履歴などの拡張機能は、最小構成の運用確認後に別Issueで判断する。

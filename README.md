# PDF分割命名ツール

## 目的

過去に開発していた `PDF分割命名ツール_v3_1_1` の元ソース消失に備え、ビルド済み配布物から仕様と実装構造を復元し、社内展開可能なデスクトップアプリとして再構築するための作業場所です。

## 状態

- 作成日: 2026-05-19
- 現在のバージョン: v0.1.5（GitHub Release 公開済み）
- 次回リリース: v0.1.8（更新直後のsidecar共有違反対策を実測値に合わせて強化し、公開準備中）
- 現在の段階: Tauri/Next.js のデスクトップアプリ本体と、Python sidecar のPDF処理部品へ整理済み。現行MVP仕様を基準に、STEP2検索支援、STEP3追加項目命名、Tauri updater 配布ライン、sidecar の対話/バルク2レーン化、PyInstaller による sidecar exe のインストーラ同梱まで実装済み。主要フローの受入は Pass 済み（詳細は `docs/05_実装状況.md`）
- 元ソース: 主要なローカル開発置き場では未発見
- ビルド済み配布物: `\\ao100\103_共有\アプリケーション\自社開発シリーズ\PDF分割命名ツール_v3_1_1`
- 解析済み入口モジュール: `pdf_splitter_app.py`
- 旧配布候補: `recovery/dist/pdf-split-naming-tool-recovery-20260521-ocrfix-rollout.zip`
- 現在のユーザー向けアプリ: `apps/desktop/`
- 現在のPDF処理部品: `recovery/pdf_splitter_tool/`
- 現段階の正本要件: `docs/01_要件定義書.md`
- 実装状況: `docs/05_実装状況.md`
- ドキュメント索引: `docs/README.md`
- デザインシステム: `docs/2026-05-31_デザインシステム.md`
- リリース手順: `apps/desktop/RELEASE.md`
- 現在のUI方針: 横ステッパーとSTEP別作業台UIを基本とし、対象一覧、主作業、補助操作をSTEPごとに最適配置する
- 画面幅方針: デスクトップPCおよび小型ノートPC幅を主対象とする。スマホ幅は表示崩れ防止のみで、実作業向け最適化は行わない
- OCR方針: 事前OCR済みPDFまたは既存テキスト層ありPDFのSTEP2検索支援は実装済み。画像PDFへのOCRエンジン内蔵、Tesseract、外部OCR API連携は後回しにする

## 現在の実装構成

ユーザーが起動して操作するアプリは `apps/desktop/` の1つです。

`recovery/pdf_splitter_tool/` は、Tauriアプリから呼び出すPython sidecarです。PDFページ数取得、プレビュー生成、分割、命名、出力前チェック、状態保存を担当します。旧Tkinter GUIは現段階の実装対象から外しており、独立した2つ目のユーザー向けアプリとしては扱いません。

UIはPDFプレビュー、ページ状態一覧、命名入力、出力前チェックを扱う業務ツールのため、PC幅での操作効率を優先します。画面は横ステッパーとSTEP別作業台UIで構成し、STEP2では左のページ状態一覧、中央プレビュー、右の分割設定/検索支援を使います。モバイル幅は確認用の表示崩れ防止に留め、スマートフォンで実作業できることはMVP受入条件に含めません。

## フォルダ

- `docs/`: 現行MVPの要件定義書、実装状況、ドキュメント索引、デザインシステム、将来構想
- `docs/archive/`: 調査結果、旧仕様、復元計画、社内展開メモ、配布前チェックリスト
- `docs/assets/`: 仕様書で参照する画像などの管理対象アセット
- `apps/desktop/`: Tauri + Next.js のデスクトップアプリ本体
- `apps/desktop/RELEASE.md`: Tauri updater と GitHub Releases によるリリース手順
- `recovery/`: Python sidecar、PDF処理ロジック、テスト。ユーザー向けGUIアプリではない
- `artifacts/analysis/`: 配布物から抽出した解析用ファイル。Git管理対象外
- `recovery/dist/`: 旧PyInstaller配布候補。Git管理対象外

## 自動回帰検証

リポジトリ単位の自動回帰検証は、ルートから次を実行します。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\verify.ps1
```

このスクリプトは Python pytest、desktop 側 JS 回帰テスト、desktop typecheck をまとめて確認するためのものです。実ブラウザ/Tauri E2E や、現場PDFを使った手動受入確認の代替ではありません。

現場PDFまたはサンプルPDFで、受入前の手元スモークを行う場合は次を実行します。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\sample-pdf-smoke.ps1 -PdfPath "C:\path\to\sample.pdf"
```

この検証は元PDFを変更せず、一時フォルダへ1ページ目のみを出力し、sidecar の `pdf_info` / preview / preflight / export / state roundtrip を確認します。実ブラウザ/Tauri E2E や、人間による受入判断の代替ではありません。

## 次に決めること

1. v0.1.5インストール版で生成PDFと260ページscan-like PDFの取込・分割・命名・出力を確認済み。現場相当の発注書PDFはsidecarスモーク実績があり、追加の本番PDFが指定された場合は同じ手順で追試する。
2. updater配布は v0.1.4 → v0.1.5 の更新検出・インストール・再起動後バージョン表示を確認済み（`npm run test:installed-updater`）。次回リリース時は同じ手順で再確認する。
3. `recovery/` のフォルダ名を将来 `sidecar/` または `backend/` へ変更するか判断する（後続課題）。
4. 画像PDFへのOCRエンジン内蔵、検索/白紙候補からの自動分割、プリセット管理、履歴などの拡張機能は、現行MVPの運用確認後に別Issueで判断する。
5. 現行 Tauri 版と次期 PySide6 版のリリースライン分離は `docs/04_移行ロードマップ.md` に方針を記載済み。移行判断はそのロードマップのフェーズゲートに従う。

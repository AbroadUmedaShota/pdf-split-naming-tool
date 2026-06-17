# Playwright E2Eテストレビュー結果

## 1. レビュー対象

- apps/desktop/e2e/desktop-shell.e2e.spec.js（TC-E2E-S1-001〜006 / TC-E2E-S1-011 / TC-E2E-S1-012 / TC-E2E-S1-020〜023 / TC-E2E-S1-025〜029 / TC-E2E-011 / TC-E2E-B6 / TC-E2E-B8 / TC-E2E-C1 / TC-E2E-C2 / TC-E2E-C3 / TC-E2E-C4 実装）
- apps/desktop/e2e/helpers.js（dev preview 共通ヘルパ）
- apps/desktop/playwright.config.js（Playwright 構成・webServer）
- apps/desktop/package.json（test:e2e スクリプト）
- テスト成果物/Playwright_E2Eテスト実装結果.md（実装結果報告）
- テスト成果物/未実装テストケース_E2E自動.md（退避 16 件）
- テスト成果物/テストケース_E2E自動.md（STEP1優先ケース / TC-E2E-011 移送後）
- 対象アプリ: apps/desktop（Next.js）http://localhost:3000 の STEP1ハーネス（?e2e=step1）と dev preview モード（?dev=<stepId>）

## 2. 参照資料

- テスト成果物/テストケース_質問待ち.md（TC-E2E-001〜018 の元定義）
- テスト成果物/テスト設計.md（3.10節 E2Eレーン・TD043-050/047b/056/068/069）
- テスト成果物/テスト設計_質問票.md（DQ03）
- apps/desktop/app/page.tsx（dev preview の挙動・各操作ハンドラの早期 return・clearSearchHighlights・search-highlight-rect セレクタ）

## 3. レビュー観点

テスト対象妥当性／トレーサビリティ／テストケース網羅／未実装管理／アサーション妥当性／偽陽性・偽陰性リスク／安定性（flake 耐性）／テスト独立性／セレクタ堅牢性／入力データ妥当性／Playwright イディオム／環境可搬性／失敗診断容易性／実行容易性／保守性。

## 4. レビュー・修正サマリー

### 第1パス（指摘 → 修正）

| 優先度 | 観点 | 問題 | 場所 | 影響 | 修正方針 |
|---|---|---|---|---|---|
| P1 | アサーション妥当性 | 初版は「次ページ」ボタン（movePage）でハイライトクリアを確認していたが、dev preview では movePage 後の loadPreview が invoke 経由で current ページ表示が追従せず、「ページ移動」が UI 上完結しないため検証意味が弱い | desktop-shell.e2e.spec.js | 「ページ移動後に残らない」の前提が弱く偽陽性リスク | 4ページ目以外の検索結果（8ページ目）クリック（selectSearchResult→selectPageForPreview）に変更。現在ページ表示 4→8 への移動完結を確認してからハイライト残留なしを判定 |
| P2 | セレクタ堅牢性 | ハイライト計数が `svg rect` ＋ `[class*="highlight"]` で、無関係な SVG を誤カウントしうる／用語チップ等を巻き込む可能性 | helpers.js countSearchHighlights | 偽陰性・偽陽性の両リスク | 実 DOM 調査で専用クラス `.search-highlight-rect` / `.search-highlight-layer` を特定し、それのみを計数するよう変更 |
| P2 | 安定性（flake 耐性） | 初期ハイライト数を即時評価しており、dev preview の非同期初期化前に 0 と判定する flake 可能性 | desktop-shell.e2e.spec.js | 初期前提の不安定 | `expect.poll` で初期ハイライト描画（total>0）と現在ページ＝4 を待機してから手順に進むよう変更 |

修正対応:

- `helpers.js`: `countSearchHighlights` を専用クラス基準（rects/layers）へ変更。`readCurrentPage`（ページ番号入力値取得）を追加。
- `desktop-shell.e2e.spec.js`: 検索結果（8ページ目）クリックでページ移動を完結させ、移動完結（現在ページ＝8）→ハイライト残留なし（rects=0・layers=0）→ JS 例外なし の順で判定するよう強化。
- 実装結果報告（`Playwright_E2Eテスト実装結果.md`）の TC-E2E-011 検証経路記述を強化版に同期。

### 第2パス（再レビュー）

- STEP1優先の追加E2E、出力先/二重起動/設定保持のSTEP1追加E2E、強化後のTC-E2E-011、STEP2/STEP3操作系E2E、STEP3追加項目E2E、1366px幅E2Eを再実行し Pass を確認。
- 残る観点（環境可搬性・実行容易性・トレーサビリティ・退避管理・独立性・flake 耐性）を再点検し、fix-worthy（P0/P1/P2）所見なしを確認。

## 5. 最終レビュー結果

- **残 P0: なし**
- **残 P1: なし**
- **残 P2: なし**
- 残 P3: Markdown 体裁 lint（MD034 bare URL・MD040 コードブロック言語・MD060 テーブル整列）が成果物 Markdown に残るが、内容・判定に影響しない体裁警告であり、他成果物との整合上も修正不要と判断。

主要な確認点:

- テスト対象妥当性: テストは baseURL=http://localhost:3000 の `?e2e=step1` と dev preview（?dev=split）を開き、対象アプリの実コードパス（openDialog / runSidecar test seam / selectPageForPreview / clearSearchHighlights）を駆動している。誤ターゲットなし。
- トレーサビリティ: TC-E2E-S1-001〜006、TC-E2E-S1-011、TC-E2E-S1-012、TC-E2E-S1-020〜023、TC-E2E-S1-025〜029、TC-E2E-011、TC-E2E-B6、TC-E2E-B8、TC-E2E-C1、TC-E2E-C2、TC-E2E-C3、TC-E2E-C4 のタイトルに TC-ID、近傍コメントに TC/Risk または TC/TD/TV/TA/Risk/Spec を保持。
- 網羅・退避: STEP1優先/追加はブラウザE2E 17件を実装、実機E2E系8件を別管理。既存E2Eレーン 18 件のうち実装 2（TC-E2E-011、TC-E2E-C3）・退避 16（TC-E2E-001〜010, 012〜017）。STEP2/STEP3操作系は6件をdev previewで実装。退避は `未実装テストケース_E2E自動.md` に具体理由（dev preview の静的 early-return で invoke モック注入不可・確認ダイアログ非発火・ステップガードのバイパス等）と必要対応・関連質問 ID（DQ03）付きで記載。質問待ち/要確認を unsupported assertion にすり替えていない。
- アサーション妥当性: 「ページ移動が完結（4→8）」かつ「前ページのハイライト矩形・レイヤーが残らない」を独立に判定。期待結果（NF-U5）に直結。
- flake 耐性: `waitForTimeout` は不使用。すべて `expect.poll` / locator 待機。
- 独立性: 単一テストで、`openDevStep` が毎回クリーンな goto から開始。

## 6. 実行結果

実行コマンド（cwd=apps/desktop）:

```text
npm run test:e2e
```

最終結果:

```text
Running 24 tests using 1 worker
24 passed
```

- TC-E2E-S1-001〜006、TC-E2E-S1-011、TC-E2E-S1-012、TC-E2E-S1-020〜023、TC-E2E-S1-025〜029、TC-E2E-011、TC-E2E-B6、TC-E2E-B8、TC-E2E-C1、TC-E2E-C2、TC-E2E-C3、TC-E2E-C4: Pass。
- webServer は既存 dev server（ポート3000）を再利用（reuseExistingServer）。テスト実行で常駐プロセスを増やさない。

最終件数: ブラウザE2E 24件 Pass。既存E2Eレーン 実装 2（Pass 2）／退避 16、STEP1優先/追加のブラウザE2E 17件、STEP2/STEP3操作系 6件。

## 7. 残課題

- fix-worthy（P0/P1/P2）の残課題なし。
- P3（体裁 lint）のみ。次アクション不要（成果物の内容・トレースに影響しない）。
- 退避 16 件は、製品コードに追加の invoke モック注入や動的状態注入の test seam を追加する判断が無い限り dev preview では自動化できない。実機E2E系はインストール版確認として別管理する。

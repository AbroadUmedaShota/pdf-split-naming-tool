import { test, expect } from '@playwright/test';
import { openDevStep, countSearchHighlights, readCurrentPage } from './helpers.js';

const step1MockPdfPath = 'C:\\Users\\tester\\Documents\\sample-step1.pdf';
const step1MockOutputDir = 'C:\\Users\\tester\\Desktop\\pdf-output';
const step1PreviewDataUrl =
  "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 420 594'%3E%3Crect width='420' height='594' fill='%23fffaf0'/%3E%3Ctext x='210' y='80' text-anchor='middle' font-family='Arial' font-size='22' fill='%232c3335'%3ESTEP1 E2E PDF%3C/text%3E%3Cline x1='72' y1='140' x2='348' y2='140' stroke='%238a8274' stroke-width='3'/%3E%3Cline x1='72' y1='200' x2='348' y2='200' stroke='%238a8274' stroke-width='3'/%3E%3Cline x1='72' y1='260' x2='348' y2='260' stroke='%238a8274' stroke-width='3'/%3E%3C/svg%3E";

async function installStep1Harness(page) {
  await page.addInitScript(
    ({ outputDir, pdfPath, previewDataUrl }) => {
      window.__PDF_TOOL_E2E_CALLS__ = [];
      window.__PDF_TOOL_E2E__ = {
        async openDialog(options) {
          window.__PDF_TOOL_E2E_CALLS__.push(options?.directory ? 'open:directory' : 'open:pdf');
          return options?.directory ? outputDir : [pdfPath];
        },
        async invokeSidecar(request) {
          window.__PDF_TOOL_E2E_CALLS__.push(request.command);
          if (request.command === 'pdf_info') {
            return {
              ok: true,
              command: 'pdf_info',
              pdf_path: request.pdf_path,
              page_count: 3,
              naming_template: '{box_no}_{binder_no}_{seq}.pdf',
            };
          }
          if (request.command === 'page_preview') {
            return {
              ok: true,
              command: 'page_preview',
              pdf_path: request.pdf_path,
              page_no: request.page_no,
              page_count: 3,
              image_data_url: previewDataUrl,
            };
          }
          return {
            ok: false,
            command: request.command,
            error: `Unexpected E2E sidecar command: ${request.command}`,
            error_type: 'UnexpectedE2ECommand',
          };
        },
      };
    },
    { outputDir: step1MockOutputDir, pdfPath: step1MockPdfPath, previewDataUrl: step1PreviewDataUrl },
  );
}

// 対象: apps/desktop（Next.js）http://localhost:3000 を STEP1 ハーネス（?e2e=step1）と
// dev preview モード（?dev=<stepId>）で検証する。
//
// 自動化方針:
//   - STEP1 はファイル選択とsidecar応答をハーネス化し、PDF取込のUI遷移を自動化する。
//   - dev preview では「決定論的に再現できる UI 観点」のみ自動化する。
//   - 処理中状態の注入・旧応答破棄・部分失敗 summary 注入・確認ダイアログ発火・リクエストゲート・
//     再採番/affix 編集の動的動作・ステップ遷移ガード（dev preview ではバイパスされる）は dev preview の
//     静的 early-return 設計で再現できないため、本ファイルでは自動化せず未実装テストケースへ退避する。
//   - dev preview で自動化したのは TC-E2E-011（検索ハイライトのページ移動後残留なし・NF-U5）。
//     dev preview のページ移動（selectPageForPreview→clearSearchHighlights）は実コードパスで動作するため、
//     期待結果「前ページのハイライトが残らない」を実 DOM で判定できる。

test.describe('PDF分割くん デスクトップ UI（dev preview）', () => {
  test('TC-E2E-S1-003 PDF選択後にPDF一覧・ページ数・プレビューが反映される', async ({ page }) => {
    // TC: TC-E2E-S1-003 | Risk: STEP1 PDF取込失敗
    // 測定手段: ?e2e=step1 で dev preview を無効化し、Tauri dialog / sidecar 応答だけをブラウザ内で差し替える。
    const pageErrors = [];
    page.on('pageerror', (err) => pageErrors.push(`pageerror: ${err.message}`));
    await installStep1Harness(page);

    await page.goto('/?e2e=step1', { waitUntil: 'networkidle' });
    await expect(page.getByRole('heading', { name: 'PDF整理ツール' })).toBeVisible();
    await expect(page.getByText('PDFが未選択です')).toBeVisible();

    await page.getByRole('button', { name: 'PDFを選択' }).first().click();

    await expect(page.getByText('sample-step1.pdf').first()).toBeVisible();
    await expect(page.getByText('3ページ').first()).toBeVisible();
    await expect
      .poll(() => page.evaluate(() => (window.__PDF_TOOL_E2E_CALLS__ ?? []).slice(0, 3)))
      .toEqual(['open:pdf', 'pdf_info', 'page_preview']);
    await expect(pageErrors, 'PDF選択からプレビュー反映まで JS 例外が発生しない').toEqual([]);
  });

  test('TC-E2E-S1-004 PDFと出力先の設定後にSTEP2へ進める', async ({ page }) => {
    // TC: TC-E2E-S1-004 | Risk: STEP1完了条件が満たされても通常フローへ進めない
    const pageErrors = [];
    page.on('pageerror', (err) => pageErrors.push(`pageerror: ${err.message}`));
    await installStep1Harness(page);

    await page.goto('/?e2e=step1', { waitUntil: 'networkidle' });
    await page.getByRole('button', { name: 'PDFを選択' }).first().click();
    await page.getByRole('button', { name: '出力フォルダ' }).click();

    const nextButton = page.getByRole('button', { name: '分割へ進む' });
    await expect(nextButton).toBeEnabled();
    await nextButton.click();

    await expect(page.locator('[data-testid="step-split"][aria-current="step"]')).toBeAttached();
    await expect(page.getByRole('button', { name: '前ページ' })).toBeVisible();
    await expect(pageErrors, 'STEP1完了からSTEP2遷移まで JS 例外が発生しない').toEqual([]);
  });

  test('TC-E2E-011 検索ハイライト表示中にページ移動すると前ページのハイライトが残らない', async ({ page }) => {
    // TC: TC-E2E-011 | TD: TD049 | TV: TV049 | TA: TA009 | Risk: R011
    // Spec: テスト設計.md TD049 / ISS-030 NF-U5（page.tsx clearSearchHighlights）
    // 測定手段: dev preview（?dev=split）。サイドカー無しでハイライト矩形のクリア挙動を実 DOM で判定する。
    //
    // dev preview の前提（app/page.tsx applyDevPreviewState / loadSearchHighlights）:
    //   - split ステップ初期表示は 4 ページ目で、用語ハイライト矩形が描画される。
    //   - loadSearchHighlights は dev preview では 4 ページ目のみ矩形を返すため、別ページへ移動すると
    //     前ページのハイライトはクリアされ、移動先には矩形が出ない（残留しないことを判定できる）。

    const pageErrors = [];
    page.on('pageerror', (err) => pageErrors.push(`pageerror: ${err.message}`));

    await openDevStep(page, 'split');

    // 前提: 初期表示は 4 ページ目で、検索ハイライトが描画されている。
    await expect
      .poll(async () => (await countSearchHighlights(page)).total, {
        message: 'ページ移動前は検索ハイライトが描画されている',
        timeout: 5000,
      })
      .toBeGreaterThan(0);
    expect(await readCurrentPage(page), '初期表示は 4 ページ目').toBe('4');

    // 手順: 4 ページ目以外の検索結果（8 ページ目）をクリックして実際にページを移動する。
    //       selectSearchResult → selectPageForPreview で currentPage が更新され、ページ移動が完結する。
    const otherPageHit = page
      .locator('.search-result-row')
      .filter({ hasText: '8ページ' })
      .first();
    await expect(otherPageHit, '4 ページ目以外の検索結果が存在する').toBeVisible();
    await otherPageHit.click();

    // ページ移動の完結を待つ（現在ページ表示が 8 になる）。
    await expect
      .poll(async () => await readCurrentPage(page), {
        message: 'クリックした 8 ページ目へ移動が完結する',
        timeout: 5000,
      })
      .toBe('8');

    // 期待結果: 移動後、前ページ（4ページ目）の検索ハイライトが DOM に残らない。
    await expect
      .poll(async () => (await countSearchHighlights(page)).total, {
        message: 'ページ移動後に前ページの検索ハイライトが残らない',
        timeout: 5000,
      })
      .toBe(0);

    const after = await countSearchHighlights(page);
    expect(after.rects, 'ページ移動後にハイライト矩形（.search-highlight-rect）が残らない').toBe(0);
    expect(after.layers, 'ページ移動後にハイライトレイヤー（.search-highlight-layer）が残らない').toBe(0);

    // 副次確認: ハイライトクリア処理でレンダリングがクラッシュしない。
    expect(pageErrors, 'ページ移動中に JS 例外が発生しない').toEqual([]);
  });
});

import { test, expect } from '@playwright/test';
import { openDevStep, countSearchHighlights, readCurrentPage } from './helpers.js';

const step1MockPdfPath = 'C:\\Users\\tester\\Documents\\sample-step1.pdf';
const step1SecondMockPdfPath = 'C:\\Users\\tester\\Documents\\second-step1.pdf';
const step1MockOutputDir = 'C:\\Users\\tester\\Desktop\\pdf-output';
const step1BrokenPdfPath = 'C:\\Users\\tester\\Documents\\broken-step1.pdf';
const step1PreviewDataUrl = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII=';

async function installStep1Harness(page, options = {}) {
  await page.addInitScript(
    ({ failPdfInfo, failedPdfPaths, openResults, outputDir, pdfPath, previewDataUrl }) => {
      const failedPathSet = new Set(failedPdfPaths);
      window.__PDF_TOOL_E2E_CALLS__ = [];
      window.__PDF_TOOL_E2E_OPEN_RESULTS__ = [...openResults];
      window.__PDF_TOOL_E2E__ = {
        async openDialog(options) {
          window.__PDF_TOOL_E2E_CALLS__.push(options?.directory ? 'open:directory' : 'open:pdf');
          if (window.__PDF_TOOL_E2E_OPEN_RESULTS__.length) {
            return window.__PDF_TOOL_E2E_OPEN_RESULTS__.shift();
          }
          return options?.directory ? outputDir : [pdfPath];
        },
        async invokeSidecar(request) {
          window.__PDF_TOOL_E2E_CALLS__.push(request.command);
          if (request.command === 'pdf_info') {
            if (failPdfInfo || failedPathSet.has(request.pdf_path)) {
              return {
                ok: false,
                command: 'pdf_info',
                error: 'PDFを開けませんでした',
                error_type: 'PdfOpenError',
              };
            }
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
          if (request.command === 'page_text') {
            return {
              ok: true,
              command: 'page_text',
              pdf_path: request.pdf_path,
              page_no: request.page_no,
              page_count: 3,
              text: 'STEP1 E2E PDF',
              has_text: true,
            };
          }
          if (request.command === 'blank_candidates') {
            return {
              ok: true,
              command: 'blank_candidates',
              pdf_path: request.pdf_path,
              threshold: request.threshold ?? 0.985,
              candidates: [],
              partial: false,
              scanned_until: 3,
            };
          }
          if (request.command === 'page_thumbnail') {
            return {
              ok: true,
              command: 'page_thumbnail',
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
    {
      failPdfInfo: Boolean(options.failPdfInfo),
      failedPdfPaths: options.failedPdfPaths ?? [],
      openResults: options.openResults ?? [],
      outputDir: step1MockOutputDir,
      pdfPath: options.pdfPath ?? step1MockPdfPath,
      previewDataUrl: step1PreviewDataUrl,
    },
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
  test('TC-E2E-S1-001 STEP1初期表示でPDF未選択状態とPDF選択ボタンが表示される', async ({ page }) => {
    // TC: TC-E2E-S1-001 | Risk: STEP1初期状態の崩れ
    const pageErrors = [];
    page.on('pageerror', (err) => pageErrors.push(`pageerror: ${err.message}`));
    await installStep1Harness(page);

    await page.goto('/?e2e=step1', { waitUntil: 'networkidle' });

    await expect(page.getByRole('heading', { name: 'PDF整理ツール' })).toBeVisible();
    await expect(page.getByText('PDFが未選択です')).toBeVisible();
    await expect(page.getByRole('button', { name: 'PDFを選択' }).first()).toBeVisible();
    await expect(page.getByRole('button', { name: '分割へ進む' })).toBeDisabled();
    await expect(page.locator('[role="status"]')).toContainText('PDFを選択してください。');
    await expect(pageErrors, 'STEP1初期表示で JS 例外が発生しない').toEqual([]);
  });

  test('TC-E2E-S1-002 PDF選択操作でファイル選択処理が呼ばれる', async ({ page }) => {
    // TC: TC-E2E-S1-002 | Risk: PDF選択ボタンがTauri dialogへ接続されない
    const pageErrors = [];
    page.on('pageerror', (err) => pageErrors.push(`pageerror: ${err.message}`));
    await installStep1Harness(page, { openResults: [[]] });

    await page.goto('/?e2e=step1', { waitUntil: 'networkidle' });
    await page.getByRole('button', { name: 'PDFを選択' }).first().click();

    await expect.poll(() => page.evaluate(() => window.__PDF_TOOL_E2E_CALLS__ ?? [])).toEqual(['open:pdf']);
    await expect(page.getByText('PDFが未選択です')).toBeVisible();
    await expect(pageErrors, 'PDF選択ダイアログ呼び出しで JS 例外が発生しない').toEqual([]);
  });

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
    await expect(page.locator('[role="status"]')).toContainText('1件のPDFを読み込みました。');
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

  test('TC-E2E-S1-005 PDF選択キャンセル時、一覧とステータスが壊れない', async ({ page }) => {
    // TC: TC-E2E-S1-005 | Risk: PDF選択キャンセルで既存一覧や完了状態が壊れる
    const pageErrors = [];
    page.on('pageerror', (err) => pageErrors.push(`pageerror: ${err.message}`));
    await installStep1Harness(page, { openResults: [[step1MockPdfPath], null] });

    await page.goto('/?e2e=step1', { waitUntil: 'networkidle' });
    await page.getByRole('button', { name: 'PDFを選択' }).first().click();
    await expect(page.getByText('sample-step1.pdf').first()).toBeVisible();
    await expect(page.locator('[role="status"]')).toContainText('1件のPDFを読み込みました。');

    await page.getByRole('button', { name: 'PDFを選択' }).first().click();

    await expect(page.getByText('sample-step1.pdf').first()).toBeVisible();
    await expect(page.getByText('3ページ').first()).toBeVisible();
    await expect(page.locator('[role="status"]')).toContainText('1件のPDFを読み込みました。');
    await expect
      .poll(() =>
        page.evaluate(() => {
          const calls = window.__PDF_TOOL_E2E_CALLS__ ?? [];
          return {
            lastCall: calls.at(-1),
            openCount: calls.filter((call) => call === 'open:pdf').length,
            pdfInfoCount: calls.filter((call) => call === 'pdf_info').length,
          };
        })
      )
      .toEqual({ lastCall: 'open:pdf', openCount: 2, pdfInfoCount: 1 });
    await expect(pageErrors, 'PDF選択キャンセルで JS 例外が発生しない').toEqual([]);
  });

  test('TC-E2E-S1-006 pdf_info失敗時、エラー表示となり一覧へ不正反映しない', async ({ page }) => {
    // TC: TC-E2E-S1-006 | Risk: 壊れたPDF情報が一覧へ混入する
    const pageErrors = [];
    page.on('pageerror', (err) => pageErrors.push(`pageerror: ${err.message}`));
    await installStep1Harness(page, { failPdfInfo: true, pdfPath: step1BrokenPdfPath });

    await page.goto('/?e2e=step1', { waitUntil: 'networkidle' });
    await page.getByRole('button', { name: 'PDFを選択' }).first().click();

    await expect(page.locator('[role="status"]')).toContainText('PDF取込エラー');
    await expect(page.locator('[role="status"]')).toContainText('PDFを開けませんでした');
    await expect(page.locator('[role="status"]')).not.toContainText('Error:');
    await expect(page.locator('.queue-row').filter({ hasText: 'broken-step1.pdf' })).toHaveCount(0);
    await expect(page.getByText('PDFが未選択です')).toBeVisible();
    await expect(page.getByRole('button', { name: '分割へ進む' })).toBeDisabled();
    await expect.poll(() => page.evaluate(() => window.__PDF_TOOL_E2E_CALLS__ ?? [])).toEqual(['open:pdf', 'pdf_info']);
    await expect(pageErrors, 'pdf_info失敗時に JS 例外が発生しない').toEqual([]);
  });

  test('TC-E2E-S1-011 複数PDF選択時に一部失敗しても読めるPDFを取り込む', async ({ page }) => {
    // TC: TC-E2E-S1-011 | Risk: 複数選択時に1件の不正PDFで全件取り込みが失敗する
    const pageErrors = [];
    page.on('pageerror', (err) => pageErrors.push(`pageerror: ${err.message}`));
    await installStep1Harness(page, {
      failedPdfPaths: [step1BrokenPdfPath],
      openResults: [[step1BrokenPdfPath, step1MockPdfPath, step1SecondMockPdfPath]],
    });

    await page.goto('/?e2e=step1', { waitUntil: 'networkidle' });
    await page.getByRole('button', { name: 'PDFを選択' }).first().click();

    await expect(page.getByText('sample-step1.pdf').first()).toBeVisible();
    await expect(page.getByText('second-step1.pdf').first()).toBeVisible();
    await expect(page.locator('.queue-row').filter({ hasText: 'broken-step1.pdf' })).toHaveCount(0);
    await expect(page.locator('.queue-row')).toHaveCount(2);
    await expect(page.locator('[role="status"]')).toContainText('2件のPDFを読み込みました。');
    await expect(page.locator('[role="status"]')).toContainText('1件は読み込めませんでした');
    await expect(page.locator('[role="status"]')).toContainText('broken-step1.pdf');
    await expect(page.locator('[role="status"]')).not.toContainText('Error:');
    await expect
      .poll(() => page.evaluate(() => (window.__PDF_TOOL_E2E_CALLS__ ?? []).filter((call) => call === 'pdf_info').length))
      .toBe(3);
    await expect
      .poll(() => page.evaluate(() => (window.__PDF_TOOL_E2E_CALLS__ ?? []).includes('page_preview')))
      .toBe(true);
    await expect(pageErrors, '一部失敗の複数PDF取込で JS 例外が発生しない').toEqual([]);
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

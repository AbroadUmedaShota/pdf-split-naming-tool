import { test, expect } from '@playwright/test';
import { openDevStep, countSearchHighlights, readCurrentPage } from './helpers.js';

const step1MockPdfPath = 'C:\\Users\\tester\\Documents\\sample-step1.pdf';
const step1SecondMockPdfPath = 'C:\\Users\\tester\\Documents\\second-step1.pdf';
const step1DesktopDir = 'C:\\Users\\tester\\Desktop';
const step1MockOutputDir = 'C:\\Users\\tester\\Desktop\\pdf-output';
const step1BrokenPdfPath = 'C:\\Users\\tester\\Documents\\broken-step1.pdf';
const step1TextPath = 'C:\\Users\\tester\\Documents\\not-pdf.txt';
const step1MissingPdfPath = 'C:\\Users\\tester\\Documents\\missing-step1.pdf';
const step1AccessDeniedPdfPath = 'C:\\Users\\tester\\Documents\\access-denied-step1.pdf';
const step1PreviewDataUrl = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII=';

async function installStep1Harness(page, options = {}) {
  await page.addInitScript(
    ({ desktopDir, failPdfInfo, failedPdfPaths, failedPreviewPaths, openDelayMs, openResults, outputDir, pdfPath, previewDataUrl }) => {
      const failedPathSet = new Set(failedPdfPaths);
      const failedPreviewPathSet = new Set(failedPreviewPaths);
      window.__PDF_TOOL_E2E_CALLS__ = [];
      window.__PDF_TOOL_E2E_OPEN_RESULTS__ = [...openResults];
      window.__PDF_TOOL_E2E__ = {
        async desktopDir() {
          return desktopDir;
        },
        async openDialog(options) {
          window.__PDF_TOOL_E2E_CALLS__.push(options?.directory ? 'open:directory' : 'open:pdf');
          if (openDelayMs) {
            await new Promise((resolve) => setTimeout(resolve, openDelayMs));
          }
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
            if (failedPreviewPathSet.has(request.pdf_path)) {
              return {
                ok: false,
                command: 'page_preview',
                error: 'プレビュー画像を生成できませんでした',
                error_type: 'PreviewError',
              };
            }
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
      desktopDir: options.desktopDir ?? step1DesktopDir,
      failPdfInfo: Boolean(options.failPdfInfo),
      failedPdfPaths: options.failedPdfPaths ?? [],
      failedPreviewPaths: options.failedPreviewPaths ?? [],
      openDelayMs: options.openDelayMs ?? 0,
      openResults: options.openResults ?? [],
      outputDir: step1MockOutputDir,
      pdfPath: options.pdfPath ?? step1MockPdfPath,
      previewDataUrl: step1PreviewDataUrl,
    },
  );
}

async function pressWindowShortcut(page, key) {
  await page.evaluate((nextKey) => {
    window.dispatchEvent(new KeyboardEvent('keydown', { key: nextKey, bubbles: true, cancelable: true }));
  }, key);
}

async function expectNoHorizontalOverflow(page, label) {
  const overflow = await page.evaluate(() => {
    const width = Math.max(document.documentElement.scrollWidth, document.body?.scrollWidth ?? 0);
    return width - document.documentElement.clientWidth;
  });
  expect(overflow, `${label} はページ全体の横スクロールを発生させない`).toBeLessThanOrEqual(2);
}

async function expectInsideViewport(locator, label) {
  const box = await locator.boundingBox();
  expect(box, `${label} が表示領域を持つ`).not.toBeNull();
  const viewport = locator.page().viewportSize();
  expect(viewport, 'viewport が取得できる').not.toBeNull();
  expect(box.x, `${label} の左端が画面外にはみ出さない`).toBeGreaterThanOrEqual(-1);
  expect(box.x + box.width, `${label} の右端が画面外にはみ出さない`).toBeLessThanOrEqual(viewport.width + 1);
}

// 対象: apps/desktop（Next.js）http://localhost:3000 を STEP1 ハーネス（?e2e=step1）と
// dev preview モード（?dev=<stepId>）で検証する。
//
// 自動化方針:
//   - STEP1 はファイル選択とsidecar応答をハーネス化し、PDF取込のUI遷移を自動化する。
//   - dev preview では「決定論的に再現できる UI 観点」のみ自動化する。
//   - 処理中状態の注入・旧応答破棄・部分失敗 summary 注入・確認ダイアログ発火・リクエストゲート・
//     再採番・ステップ遷移ガード（dev preview ではバイパスされる）は dev preview の
//     静的 early-return 設計で再現できないため、本ファイルでは自動化せず未実装テストケースへ退避する。
//   - dev preview で自動化したのは TC-E2E-011（検索ハイライト残留なし）、TC-E2E-B6/B8/C1/C2/C3/C4。
//     dev preview でも実コードパスで動くページ移動、入力編集、候補選択、表示モード、レイアウトを実 DOM で判定する。

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

  test('TC-E2E-S1-023 取込失敗時の画面表示とコンソール状態を証跡化できる', async ({ page }, testInfo) => {
    // TC: TC-E2E-S1-023 | Risk: 取込失敗時の証跡不足で原因確認や受入判断ができない
    const consoleErrors = [];
    const pageErrors = [];
    page.on('console', (message) => {
      if (message.type() === 'error') {
        consoleErrors.push(message.text());
      }
    });
    page.on('pageerror', (err) => pageErrors.push(`pageerror: ${err.message}`));
    await installStep1Harness(page, { failPdfInfo: true, pdfPath: step1BrokenPdfPath });

    await page.goto('/?e2e=step1', { waitUntil: 'networkidle' });
    await page.getByRole('button', { name: 'PDFを選択' }).first().click();

    const status = page.locator('[role="status"]');
    await expect(status).toContainText('PDF取込エラー');
    await expect(status).toContainText('PDFを開けませんでした');
    await expect(status).not.toContainText('Error:');
    await expect(page.locator('.queue-row')).toHaveCount(0);
    await expect(page.getByRole('button', { name: '分割へ進む' })).toBeDisabled();

    const evidence = {
      consoleErrors,
      nextDisabled: await page.getByRole('button', { name: '分割へ進む' }).isDisabled(),
      pageErrors,
      queueRows: await page.locator('.queue-row').count(),
      statusText: await status.innerText(),
    };
    await testInfo.attach('TC-E2E-S1-023-error-state.json', {
      body: JSON.stringify(evidence, null, 2),
      contentType: 'application/json',
    });
    await testInfo.attach('TC-E2E-S1-023-error-state.png', {
      body: await page.screenshot({ fullPage: false }),
      contentType: 'image/png',
    });

    expect(consoleErrors, '取込失敗表示でブラウザ console error が発生しない').toEqual([]);
    expect(pageErrors, '取込失敗表示で JS 例外が発生しない').toEqual([]);
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

  test('TC-E2E-S1-025 複数PDFを同時選択して全件成功時に一覧順・件数・プレビューが反映される', async ({ page }) => {
    // TC: TC-E2E-S1-025 | Risk: 複数PDF全件成功時に一覧順や初回プレビューが崩れる
    const pageErrors = [];
    page.on('pageerror', (err) => pageErrors.push(`pageerror: ${err.message}`));
    await installStep1Harness(page, {
      openResults: [[step1MockPdfPath, step1SecondMockPdfPath]],
    });

    await page.goto('/?e2e=step1', { waitUntil: 'networkidle' });
    await page.getByRole('button', { name: 'PDFを選択' }).first().click();

    await expect(page.locator('.queue-row')).toHaveCount(2);
    await expect(page.locator('.queue-row').nth(0)).toContainText('sample-step1.pdf');
    await expect(page.locator('.queue-row').nth(1)).toContainText('second-step1.pdf');
    await expect(page.locator('.queue-row.selected')).toContainText('sample-step1.pdf');
    await expect(page.getByText('3ページ').first()).toBeVisible();
    await expect(page.locator('[role="status"]')).toContainText('2件のPDFを読み込みました。');
    await expect(page.locator('[role="status"]')).not.toContainText('読み込めませんでした');
    await expect
      .poll(() =>
        page.evaluate(() => {
          const calls = window.__PDF_TOOL_E2E_CALLS__ ?? [];
          return {
            pdfInfoCount: calls.filter((call) => call === 'pdf_info').length,
            previewCount: calls.filter((call) => call === 'page_preview').length,
          };
        })
      )
      .toEqual({ pdfInfoCount: 2, previewCount: 1 });
    await page.getByRole('button', { name: '出力フォルダ' }).click();
    const nextButton = page.getByRole('button', { name: '分割へ進む' });
    await expect(nextButton).toBeEnabled();
    await nextButton.click();
    await expect(page.locator('[data-testid="step-split"][aria-current="step"]')).toBeAttached();
    await expect(page.getByAltText('PDFページプレビュー')).toBeVisible();
    await expect(pageErrors, '複数PDF全件成功の取込で JS 例外が発生しない').toEqual([]);
  });

  test('TC-E2E-S1-026 初回プレビュー失敗時もPDFは一覧に残り取込済みとして切り分けできる', async ({ page }) => {
    // TC: TC-E2E-S1-026 | Risk: PDF情報取得後のプレビュー失敗がPDF取込失敗に見えて原因切り分けできない
    const pageErrors = [];
    page.on('pageerror', (err) => pageErrors.push(`pageerror: ${err.message}`));
    await installStep1Harness(page, {
      failedPreviewPaths: [step1MockPdfPath],
      openResults: [[step1MockPdfPath]],
    });

    await page.goto('/?e2e=step1', { waitUntil: 'networkidle' });
    await page.getByRole('button', { name: 'PDFを選択' }).first().click();

    await expect(page.locator('.queue-row')).toHaveCount(1);
    await expect(page.locator('.queue-row')).toContainText('sample-step1.pdf');
    await expect(page.locator('.queue-row')).toContainText('3ページ');
    await expect(page.locator('.queue-row.selected')).toContainText('sample-step1.pdf');
    await expect(page.locator('[role="status"]')).toContainText('1件のPDFを読み込みましたが、プレビューを表示できませんでした');
    await expect(page.locator('[role="status"]')).toContainText('プレビュー画像を生成できませんでした');
    await expect(page.locator('[role="status"]')).not.toContainText('PDF取込エラー');
    await expect(page.getByRole('button', { name: '分割へ進む' })).toBeEnabled();
    await expect.poll(() => page.evaluate(() => (window.__PDF_TOOL_E2E_CALLS__ ?? []).slice(0, 3))).toEqual([
      'open:pdf',
      'pdf_info',
      'page_preview',
    ]);
    await expect(pageErrors, '初回プレビュー失敗で JS 例外が発生しない').toEqual([]);
  });

  test('TC-E2E-S1-020 PDF以外と存在しないパスは一覧へ不正反映せず復旧できる', async ({ page }) => {
    // TC: TC-E2E-S1-020 | Risk: PDF以外や存在しない/アクセス不可パスが一覧に混入して後続処理を壊す
    const pageErrors = [];
    page.on('pageerror', (err) => pageErrors.push(`pageerror: ${err.message}`));
    await installStep1Harness(page, {
      failedPdfPaths: [step1MissingPdfPath, step1AccessDeniedPdfPath],
      openResults: [[step1TextPath, step1MissingPdfPath, step1AccessDeniedPdfPath], [step1MockPdfPath]],
    });

    await page.goto('/?e2e=step1', { waitUntil: 'networkidle' });
    await page.getByRole('button', { name: 'PDFを選択' }).first().click();

    await expect(page.locator('[role="status"]')).toContainText('PDF取込エラー');
    await expect(page.locator('[role="status"]')).toContainText('not-pdf.txt');
    await expect(page.locator('[role="status"]')).toContainText('PDFファイルではありません。');
    await expect(page.locator('[role="status"]')).toContainText('missing-step1.pdf');
    await expect(page.locator('[role="status"]')).toContainText('access-denied-step1.pdf');
    await expect(page.locator('.queue-row')).toHaveCount(0);
    await expect(page.getByText('PDFが未選択です')).toBeVisible();
    await expect(page.getByRole('button', { name: '分割へ進む' })).toBeDisabled();

    await page.getByRole('button', { name: 'PDFを選択' }).first().click();
    await expect(page.locator('.queue-row')).toHaveCount(1);
    await expect(page.getByText('sample-step1.pdf').first()).toBeVisible();
    await expect(page.locator('[role="status"]')).toContainText('1件のPDFを読み込みました。');
    await expect(pageErrors, 'PDF以外/存在しないパスの復旧で JS 例外が発生しない').toEqual([]);
  });

  test('TC-E2E-S1-012 PDF選択待ち中に取込ボタンが無効化される', async ({ page }) => {
    // TC: TC-E2E-S1-012 | Risk: OSファイル選択待ち中に無反応/連打できるように見える
    const pageErrors = [];
    page.on('pageerror', (err) => pageErrors.push(`pageerror: ${err.message}`));
    await installStep1Harness(page, { openDelayMs: 3000 });

    await page.goto('/?e2e=step1', { waitUntil: 'networkidle' });
    await page.getByRole('button', { name: 'PDFを選択' }).first().click();

    await expect(page.locator('[role="status"]')).toContainText('PDFを選択しています');
    await expect(page.getByRole('button', { name: '選択中' }).first()).toBeDisabled();
    await expect(page.getByText('sample-step1.pdf').first()).toBeVisible();
    await expect(page.locator('[role="status"]')).toContainText('1件のPDFを読み込みました。');
    await expect(pageErrors, 'PDF選択待ち表示で JS 例外が発生しない').toEqual([]);
  });

  test('TC-E2E-S1-022 取込後に1件削除・全クリア・再取込してSTEP2へ進める', async ({ page }) => {
    // TC: TC-E2E-S1-022 | Risk: STEP1で取り込み直しが必要になった時に復旧できない
    const pageErrors = [];
    page.on('pageerror', (err) => pageErrors.push(`pageerror: ${err.message}`));
    await installStep1Harness(page, {
      openResults: [[step1MockPdfPath, step1SecondMockPdfPath], [step1MockPdfPath]],
    });

    await page.goto('/?e2e=step1', { waitUntil: 'networkidle' });
    await page.getByRole('button', { name: 'PDFを選択' }).first().click();

    await expect(page.locator('.queue-row')).toHaveCount(2);
    await expect(page.getByText('sample-step1.pdf').first()).toBeVisible();
    await expect(page.getByText('second-step1.pdf').first()).toBeVisible();
    await expect(page.locator('[role="status"]')).toContainText('2件のPDFを読み込みました。');

    await page.getByRole('button', { name: 'sample-step1.pdf を一覧から外す' }).click();
    await expect(page.locator('.queue-row')).toHaveCount(1);
    await expect(page.locator('.queue-row')).toContainText('second-step1.pdf');
    await expect(page.locator('.queue-row').filter({ hasText: 'sample-step1.pdf' })).toHaveCount(0);
    await expect(page.locator('[role="status"]')).toContainText('sample-step1.pdf を一覧から外しました。');

    await page.getByRole('button', { name: '全クリア' }).first().click();
    await expect(page.locator('.queue-row')).toHaveCount(0);
    await expect(page.getByText('PDFが未選択です')).toBeVisible();
    await expect(page.locator('[role="status"]')).toContainText('PDF一覧をクリアしました。');
    await expect(page.getByRole('button', { name: '分割へ進む' })).toBeDisabled();

    await page.getByRole('button', { name: 'PDFを選択' }).first().click();
    await expect(page.locator('.queue-row')).toHaveCount(1);
    await expect(page.getByText('sample-step1.pdf').first()).toBeVisible();
    await expect(page.getByText('3ページ').first()).toBeVisible();
    await expect(page.locator('[role="status"]')).toContainText('1件のPDFを読み込みました。');

    await page.getByRole('button', { name: '出力フォルダ' }).click();
    const nextButton = page.getByRole('button', { name: '分割へ進む' });
    await expect(nextButton).toBeEnabled();
    await nextButton.click();
    await expect(page.locator('[data-testid="step-split"][aria-current="step"]')).toBeAttached();
    await expect(pageErrors, 'PDF削除・全クリア・再取込で JS 例外が発生しない').toEqual([]);
  });

  test('TC-E2E-S1-021 複数PDFを連続追加しても重複せず現在選択PDFを維持する', async ({ page }) => {
    // TC: TC-E2E-S1-021 | Risk: 連続追加や重複選択で一覧順・現在PDFが壊れる
    const pageErrors = [];
    page.on('pageerror', (err) => pageErrors.push(`pageerror: ${err.message}`));
    await installStep1Harness(page, {
      openResults: [[step1MockPdfPath], [step1MockPdfPath, step1SecondMockPdfPath], [step1MockPdfPath]],
    });

    await page.goto('/?e2e=step1', { waitUntil: 'networkidle' });
    await page.getByRole('button', { name: 'PDFを選択' }).first().click();
    await expect(page.locator('.queue-row')).toHaveCount(1);
    await expect(page.locator('.queue-row').nth(0)).toContainText('sample-step1.pdf');

    await page.getByRole('button', { name: 'PDFを選択' }).first().click();
    await expect(page.locator('.queue-row')).toHaveCount(2);
    await expect(page.locator('.queue-row').nth(0)).toContainText('sample-step1.pdf');
    await expect(page.locator('.queue-row').nth(1)).toContainText('second-step1.pdf');
    await expect(page.locator('[role="status"]')).toContainText('1件のPDFを読み込みました。');
    await expect(page.locator('[role="status"]')).toContainText('1件は追加済みです。');

    await page.locator('.queue-row').filter({ hasText: 'second-step1.pdf' }).locator('.queue-main').click();
    await expect(page.locator('.queue-row.selected')).toContainText('second-step1.pdf');

    await page.getByRole('button', { name: 'PDFを選択' }).first().click();
    await expect(page.locator('.queue-row')).toHaveCount(2);
    await expect(page.locator('.queue-row.selected')).toContainText('second-step1.pdf');
    await expect(page.locator('[role="status"]')).toContainText('選択したPDFはすでに一覧にあります。');
    await expect(pageErrors, 'PDF連続追加・重複排除で JS 例外が発生しない').toEqual([]);
  });

  test('TC-E2E-S1-027 出力先のキャンセル・再設定・デスクトップ戻しでSTEP1完了条件が壊れない', async ({ page }) => {
    // TC: TC-E2E-S1-027 | Risk: 出力先キャンセルや戻し操作でSTEP1完了条件が不正になる
    const pageErrors = [];
    page.on('pageerror', (err) => pageErrors.push(`pageerror: ${err.message}`));
    await installStep1Harness(page, {
      openResults: [[step1MockPdfPath], null, step1MockOutputDir],
    });

    await page.goto('/?e2e=step1', { waitUntil: 'networkidle' });
    await page.getByRole('button', { name: 'PDFを選択' }).first().click();

    const nextButton = page.getByRole('button', { name: '分割へ進む' });
    await expect(page.locator('.queue-row')).toHaveCount(1);
    await expect(page.locator('.path-line')).toContainText(step1DesktopDir);
    await expect(nextButton).toBeEnabled();

    await page.getByRole('button', { name: '出力フォルダ' }).click();
    await expect(page.locator('.path-line')).toContainText(step1DesktopDir);
    await expect(nextButton).toBeEnabled();

    await page.getByRole('button', { name: '出力フォルダ' }).click();
    await expect(page.locator('.path-line')).toContainText(step1MockOutputDir);
    await expect(page.locator('[role="status"]')).toContainText('出力フォルダを設定しました。');
    await expect(nextButton).toBeEnabled();

    await page.getByRole('button', { name: 'デスクトップへ戻す' }).click();
    await expect(page.locator('.path-line')).toContainText(step1DesktopDir);
    await expect(page.locator('[role="status"]')).toContainText('出力先をデスクトップに戻しました。');
    await expect(nextButton).toBeEnabled();
    await expect
      .poll(() => page.evaluate(() => (window.__PDF_TOOL_E2E_CALLS__ ?? []).filter((call) => call === 'open:directory').length))
      .toBe(2);
    await expect(pageErrors, '出力先キャンセル・再設定・戻しで JS 例外が発生しない').toEqual([]);
  });

  test('TC-E2E-S1-028 PDF選択中に再クリックしても取込ダイアログは二重起動しない', async ({ page }) => {
    // TC: TC-E2E-S1-028 | Risk: 取込中の二重起動で一覧・ステータス・sidecar呼び出しが競合する
    const pageErrors = [];
    page.on('pageerror', (err) => pageErrors.push(`pageerror: ${err.message}`));
    await installStep1Harness(page, { openDelayMs: 500 });

    await page.goto('/?e2e=step1', { waitUntil: 'networkidle' });
    await page.getByRole('button', { name: 'PDFを選択' }).first().evaluate((button) => {
      button.click();
      button.click();
    });

    await expect(page.locator('[role="status"]')).toContainText('PDFを選択しています');
    await expect
      .poll(() => page.evaluate(() => (window.__PDF_TOOL_E2E_CALLS__ ?? []).filter((call) => call === 'open:pdf').length))
      .toBe(1);
    await expect(page.locator('.queue-row')).toHaveCount(1);
    await expect(page.locator('[role="status"]')).toContainText('1件のPDFを読み込みました。');
    await expect(pageErrors, 'PDF選択中の再クリックで JS 例外が発生しない').toEqual([]);
  });

  test('TC-E2E-S1-029 PDF追加後も出力先と共通項目を維持する', async ({ page }) => {
    // TC: TC-E2E-S1-029 | Risk: PDF追加で出力先や共通項目が消え、STEP1をやり直す必要が出る
    const pageErrors = [];
    page.on('pageerror', (err) => pageErrors.push(`pageerror: ${err.message}`));
    await installStep1Harness(page, {
      openResults: [[step1MockPdfPath], step1MockOutputDir, [step1SecondMockPdfPath]],
    });

    await page.goto('/?e2e=step1', { waitUntil: 'networkidle' });
    await page.getByRole('button', { name: 'PDFを選択' }).first().click();
    await page.getByRole('button', { name: '出力フォルダ' }).click();
    await page.locator('input[name="common_box_no"]').fill('12');
    await page.locator('input[name="common_binder_no"]').fill('34');

    await page.getByRole('button', { name: 'PDFを選択' }).first().click();

    await expect(page.locator('.queue-row')).toHaveCount(2);
    await expect(page.locator('.path-line')).toContainText(step1MockOutputDir);
    await expect(page.locator('input[name="common_box_no"]')).toHaveValue('12');
    await expect(page.locator('input[name="common_binder_no"]')).toHaveValue('34');
    await expect(page.getByRole('button', { name: '分割へ進む' })).toBeEnabled();
    await expect(pageErrors, 'PDF追加後の出力先・共通項目維持で JS 例外が発生しない').toEqual([]);
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
    // 検索結果は「検索・補助ツール」アコーディオンに畳まれているので先に開く。
    await page.locator('.assist-accordion > summary').click();

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

  test('TC-E2E-B6 プレビューの表示モード・スライダー・Ctrlホイールでズーム状態が反映される', async ({ page }) => {
    // TC: manual B6/B7 | Risk: プレビュー拡大縮小が表示へ反映されず操作確認できない
    const pageErrors = [];
    page.on('pageerror', (err) => pageErrors.push(`pageerror: ${err.message}`));

    await openDevStep(page, 'split');

    const previewFrame = page.locator('.preview-frame');
    const zoomGroup = page.locator('.zoom-controls');
    const zoomSlider = page.getByLabel('ズーム倍率');

    await expect(previewFrame).toHaveClass(/page/);
    await page.getByRole('button', { name: '幅合わせ' }).click();
    await expect(previewFrame).toHaveClass(/width/);
    await expect(page.getByRole('button', { name: '幅合わせ' })).toHaveClass(/selected/);

    await page.getByRole('button', { name: '全体表示' }).click();
    await expect(previewFrame).toHaveClass(/page/);
    await expect(page.getByRole('button', { name: '全体表示' })).toHaveClass(/selected/);

    await page.getByRole('button', { name: '実寸' }).click();
    await expect(previewFrame).toHaveClass(/free/);
    await expect(zoomSlider).toHaveValue('1');
    await expect(zoomGroup).toContainText('100%');

    await zoomSlider.focus();
    await page.keyboard.press('ArrowRight');
    await expect(previewFrame).toHaveClass(/free/);
    await expect(zoomSlider).toHaveValue('1.1');
    await expect(zoomGroup).toContainText('110%');

    await previewFrame.dispatchEvent('wheel', { bubbles: true, cancelable: true, ctrlKey: true, deltaY: -120 });
    await expect(zoomSlider).toHaveValue('1.2');
    await expect(zoomGroup).toContainText('120%');

    await previewFrame.dispatchEvent('wheel', { bubbles: true, cancelable: true, ctrlKey: false, deltaY: -120 });
    await expect(zoomSlider).toHaveValue('1.2');
    await expect(zoomGroup).toContainText('120%');

    expect(pageErrors, 'ズーム操作で JS 例外が発生しない').toEqual([]);
  });

  test('TC-E2E-B7 STEP2プレビューを通常ホイールとEnterで縦スクロールできる', async ({ page }) => {
    await openDevStep(page, 'split');

    const previewFrame = page.getByLabel('PDFページプレビュー');
    await page.getByRole('button', { name: '実寸' }).click();
    await page.getByLabel('ズーム倍率').fill('2.4');
    // dev preview は sidecar の倍率別再描画を行わないため、拡大時と同じ縦overflowを再現する。
    await previewFrame.locator('.preview-page-layer').evaluate((element) => {
      element.style.minHeight = '1600px';
    });
    await expect.poll(async () => previewFrame.evaluate((element) => element.scrollHeight > element.clientHeight)).toBe(true);

    await previewFrame.hover();
    await page.mouse.wheel(0, 480);
    await expect.poll(async () => previewFrame.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);

    await previewFrame.evaluate((element) => { element.scrollTop = 0; });
    await previewFrame.focus();
    await page.keyboard.press('Enter');
    await expect.poll(async () => previewFrame.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);

    await page.keyboard.press('Shift+Enter');
    await expect.poll(async () => previewFrame.evaluate((element) => element.scrollTop)).toBe(0);
  });

  test('TC-E2E-B8 STEP2/STEP3の矢印ナビと入力欄フォーカス中のガードが動作する', async ({ page }) => {
    // TC: manual B8 | Risk: キーボード操作がページ/セグメント移動と入力編集で衝突する
    const pageErrors = [];
    page.on('pageerror', (err) => pageErrors.push(`pageerror: ${err.message}`));

    await openDevStep(page, 'split');
    await page.locator('.preview-frame').click();
    expect(await readCurrentPage(page), 'STEP2初期表示は4ページ目').toBe('4');
    await pressWindowShortcut(page, 'ArrowRight');
    await expect.poll(async () => await readCurrentPage(page)).toBe('5');
    await pressWindowShortcut(page, 'ArrowLeft');
    await expect.poll(async () => await readCurrentPage(page)).toBe('4');

    await openDevStep(page, 'input');
    const selectedRow = page.locator('.mini-row.selected');
    await expect(selectedRow).toContainText('4-7');
    expect(await readCurrentPage(page), 'STEP3初期表示は選択セグメント先頭').toBe('4');

    await page.locator('.preview-frame').click();
    await pressWindowShortcut(page, 'ArrowDown');
    await expect(selectedRow).toContainText('8-11');
    await expect.poll(async () => await readCurrentPage(page)).toBe('8');
    await pressWindowShortcut(page, 'ArrowUp');
    await expect(selectedRow).toContainText('4-7');
    await expect.poll(async () => await readCurrentPage(page)).toBe('4');
    await pressWindowShortcut(page, 'ArrowRight');
    await expect.poll(async () => await readCurrentPage(page)).toBe('5');

    await page.locator('input[name="box_no"]').focus();
    await page.keyboard.press('ArrowRight');
    await expect.poll(async () => await readCurrentPage(page), {
      message: '入力欄フォーカス中は矢印キーでページ移動しない',
    }).toBe('5');

    expect(pageErrors, '矢印ナビ操作で JS 例外が発生しない').toEqual([]);
  });

  test('TC-E2E-B9 STEP2でクリック位置に依存せず分割・移動ショートカットが効き一覧が追従する', async ({ page }) => {
    // Risk: ボタン/入力欄をクリックした後にフォーカスが奪われ、Space/矢印の分割・移動が効かなくなる
    const pageErrors = [];
    page.on('pageerror', (err) => pageErrors.push(`pageerror: ${err.message}`));

    await openDevStep(page, 'split');
    expect(await readCurrentPage(page), 'STEP2初期表示は4ページ目').toBe('4');

    // ページ番号入力（テキスト入力）にフォーカス中は、従来どおり矢印でページ移動しない（入力編集を優先）。
    await page.locator('input[aria-label="ページ番号"]').focus();
    await page.keyboard.press('ArrowRight');
    await expect.poll(async () => await readCurrentPage(page), {
      message: 'ページ番号入力フォーカス中は矢印でページ移動しない',
    }).toBe('4');

    // 入力欄以外（プレビュー枠）をクリックすると中立フォーカスへ逃げ、実キーの矢印でページ移動できる。
    await page.locator('.preview-frame').click();
    await page.keyboard.press('ArrowRight');
    await expect.poll(async () => await readCurrentPage(page)).toBe('5');

    // 表示モードのボタン（フォーカス可能）をクリックした後でも、実キーの Space で分割を追加できる。
    const markerCountBefore = await page.locator('.split-marker').count();
    await page.getByRole('button', { name: '幅合わせ' }).click();
    await page.keyboard.press(' ');
    await expect(page.locator('.split-marker')).toHaveCount(markerCountBefore + 1);
    await expect(page.locator('.page-state-row.split-before').filter({ hasText: '5ページ' })).toHaveCount(1);

    // ページ状態一覧の追従: 最終ページへ移動しても現在行が表示領域内に留まる。
    await page.locator('input[aria-label="ページ番号"]').fill('11');
    await expect.poll(async () => await readCurrentPage(page)).toBe('11');
    const selectedRow = page.locator('.page-state-row.selected');
    await expect(selectedRow).toContainText('11ページ');
    await expect(selectedRow).toBeInViewport();

    expect(pageErrors, 'クリック位置非依存のショートカット操作で JS 例外が発生しない').toEqual([]);
  });

  test('TC-E2E-C1 STEP2検索支援で用語選択・検索結果・OCR強調・ハイライトが表示される', async ({ page }) => {
    // TC: manual C1 | Risk: 検索支援が分割判断の補助として使えない
    const pageErrors = [];
    page.on('pageerror', (err) => pageErrors.push(`pageerror: ${err.message}`));

    await openDevStep(page, 'split');
    // 検索・候補・白紙は「検索・補助ツール」アコーディオンに畳まれているので先に開く。
    await page.locator('.assist-accordion > summary').click();

    const selectedTerms = page.getByLabel('選択中のハイライト用語');
    await expect(selectedTerms).toContainText('契約書');
    await expect(selectedTerms).toContainText('請求書');

    await page.getByRole('button', { name: '用語を選択' }).click();
    await expect(page.getByRole('dialog', { name: 'ハイライト対象用語' })).toBeVisible();
    await page.getByRole('button', { name: '閉じる' }).click();

    await page.getByRole('button', { name: '検索/ハイライト' }).click();
    await expect(page.locator('[role="status"]')).toContainText('DEVプレビューの検索結果を表示しました。');
    await expect(page.locator('.search-result-row')).toHaveCount(2);
    await expect(page.locator('.search-result-row').nth(0)).toContainText('4ページ');
    await expect(page.locator('.search-result-row').nth(0)).toContainText('契約書 / 請求書');
    await expect(page.locator('.ocr-search-mark')).toHaveCount(2);
    await expect
      .poll(async () => (await countSearchHighlights(page)).total, {
        message: '検索後にプレビュー上のハイライトが表示される',
        timeout: 5000,
      })
      .toBeGreaterThan(0);

    expect(pageErrors, '検索支援操作で JS 例外が発生しない').toEqual([]);
  });

  test('TC-E2E-C2 STEP2候補表示でインデックス候補と白紙候補から該当ページへ移動できる', async ({ page }) => {
    // TC: manual C2 | Risk: 候補ページを分割判断の起点として確認できない
    const pageErrors = [];
    page.on('pageerror', (err) => pageErrors.push(`pageerror: ${err.message}`));

    await openDevStep(page, 'split');
    // 候補・白紙は「検索・補助ツール」アコーディオンに畳まれているので先に開く。
    await page.locator('.assist-accordion > summary').click();

    await page.getByRole('button', { name: '候補取得' }).click();
    await expect(page.locator('[role="status"]')).toContainText('DEVプレビューの候補検索結果を表示しました。');
    await expect(page.locator('.index-candidate-row')).toHaveCount(3);
    await expect(page.locator('.index-candidate-row').nth(0)).toContainText('1ページ');
    await expect(page.locator('.index-candidate-row').nth(0)).toContainText('表紙');
    await expect(page.locator('.blank-candidate-row')).toHaveCount(1);
    await expect(page.locator('.blank-candidate-row')).toContainText('11ページ');

    await page.locator('.index-candidate-row').filter({ hasText: '1ページ' }).click();
    await expect.poll(async () => await readCurrentPage(page)).toBe('1');

    await page.locator('.blank-candidate-row').filter({ hasText: '11ページ' }).click();
    await expect.poll(async () => await readCurrentPage(page)).toBe('11');

    expect(pageErrors, '候補表示操作で JS 例外が発生しない').toEqual([]);
  });

  test('TC-E2E-C3 STEP3追加項目を追加・削除・再追加して出力名へ反映できる', async ({ page }) => {
    // TC: manual C3 / TD069 | Risk: 追加項目の削除・再追加で旧値が復活し誤命名する
    const pageErrors = [];
    page.on('pageerror', (err) => pageErrors.push(`pageerror: ${err.message}`));

    await openDevStep(page, 'input');

    const filenamePreview = page.locator('.filename-preview strong');
    await expect(filenamePreview).toHaveText('01_01_002.pdf');
    // セグメント一覧の命名列は、出力名プレビューと同じ実ファイル名を表示する（表記ゆれ無し）。
    await expect(page.locator('.mini-row.selected')).toContainText('01_01_002.pdf');

    await page.getByRole('button', { name: /追加（最大2件）/ }).click();
    await page.getByLabel('追加項目1の値').fill('契約A');
    await expect(filenamePreview).toHaveText('01_01_002_契約A.pdf');

    await page.getByLabel('追加項目1の挿入位置').selectOption('prefix');
    await expect(filenamePreview).toHaveText('契約A_01_01_002.pdf');
    await page.getByRole('button', { name: '一括適用' }).click();
    await expect(page.locator('.status-pill')).toContainText('全セグメントへ適用しました');

    page.once('dialog', async (dialog) => {
      await dialog.accept();
    });
    await page.getByRole('button', { name: '追加項目1を削除' }).click();
    await expect(page.getByLabel('追加項目1の値')).toHaveCount(0);
    await expect(filenamePreview).toHaveText('01_01_002.pdf');

    await page.getByRole('button', { name: /追加（最大2件）/ }).click();
    await expect(page.getByLabel('追加項目1の値')).toHaveValue('');
    await expect(filenamePreview).not.toContainText('契約A');

    await page.locator('.mini-row').filter({ hasText: '8-11' }).click();
    await expect(page.getByLabel('追加項目1の値')).toHaveValue('');
    await expect(filenamePreview).toHaveText('01_01_003.pdf');
    await expect(page.locator('.mini-row.selected')).toContainText('01_01_003.pdf');

    await page.getByLabel('追加項目1の値').fill('再追加');
    await expect(filenamePreview).toHaveText('01_01_003_再追加.pdf');

    expect(pageErrors, '追加項目の追加・削除・再追加で JS 例外が発生しない').toEqual([]);
  });

  test('TC-E2E-C4 1366px幅でSTEP2/STEP3の主要操作面が画面内に収まる', async ({ page }) => {
    // TC: manual C4 / TD065 | Risk: 業務PC幅でプレビュー・操作群・右ペインが見切れる
    const pageErrors = [];
    page.on('pageerror', (err) => pageErrors.push(`pageerror: ${err.message}`));
    await page.setViewportSize({ width: 1366, height: 768 });

    await openDevStep(page, 'split');
    await expectNoHorizontalOverflow(page, 'STEP2 1366px');
    await expectInsideViewport(page.locator('.task-layout.split-focused-layout'), 'STEP2 レイアウト');
    await expectInsideViewport(page.locator('.split-list'), 'STEP2 左ペイン');
    await expectInsideViewport(page.locator('.split-work'), 'STEP2 プレビュー');
    await expectInsideViewport(page.getByLabel('STEP2詳細操作'), 'STEP2 右ペイン');
    await expect(page.getByRole('button', { name: '現在ページの前で分割' })).toBeVisible();

    await openDevStep(page, 'input');
    await expectNoHorizontalOverflow(page, 'STEP3 1366px');
    await expectInsideViewport(page.locator('.task-layout.input-focused-layout'), 'STEP3 レイアウト');
    await expectInsideViewport(page.locator('.pane.stack').first(), 'STEP3 セグメント一覧');
    await expectInsideViewport(page.locator('.input-work'), 'STEP3 入力プレビュー');
    await expectInsideViewport(page.getByLabel('STEP3命名入力'), 'STEP3 命名入力');
    await expect(page.locator('.filename-preview strong')).toBeVisible();

    expect(pageErrors, '1366px幅レイアウト確認で JS 例外が発生しない').toEqual([]);
  });

  test('TC-E2E-D1 STEP4で出力先変更導線・状態メッセージ全文・要修正ガイドが揃う', async ({ page }) => {
    // Risk: 既存衝突時に「出力先を変更」と促されるのに、その場で変更できず・メッセージも見切れる
    const pageErrors = [];
    page.on('pageerror', (err) => pageErrors.push(`pageerror: ${err.message}`));

    await openDevStep(page, 'output');

    // A1: 出力先を変更ボタンが STEP4 にある（STEP1 へ戻らず変更できる導線）。
    await expect(page.getByRole('button', { name: '出力先を変更' })).toBeEnabled();

    // A2: 既存衝突行の状態メッセージが見切れず、title でフル文を保持する。
    const existingMsg = '同名ファイルが既存です。出力先を変更するか既存ファイルを削除してください';
    const stateCell = page.locator('.check-row.error .check-state-cell');
    await expect(stateCell).toHaveAttribute('title', existingMsg);
    await expect(stateCell).toContainText('既存ファイルを削除してください');

    // A3: 要修正がある時、次アクションの一行ガイドが出る。
    await expect(page.locator('.output-issue-hint')).toContainText('要修正の行があります');

    expect(pageErrors, 'STEP4出力UXで JS 例外が発生しない').toEqual([]);
  });

  test('TC-E2E-D2 主要行・ダイアログ起動ボタンにアクセシブルネームが付く', async ({ page }) => {
    // Risk: ページ行/命名行/モーダル起動が支援技術に役割・対象を伝えられない
    const pageErrors = [];
    page.on('pageerror', (err) => pageErrors.push(`pageerror: ${err.message}`));

    await openDevStep(page, 'split');
    // B1: STEP2ページ行が「Nページを選択」で識別できる。
    await expect(page.getByRole('button', { name: '4ページを選択' })).toBeVisible();
    // B4: 用語を選択ボタンがダイアログ起動であることを支援技術へ通知する。
    // 「検索・補助ツール」アコーディオンに畳まれているので先に開く。
    await page.locator('.assist-accordion > summary').click();
    await expect(page.getByRole('button', { name: '用語を選択' })).toHaveAttribute('aria-haspopup', 'dialog');

    await openDevStep(page, 'input');
    // B2: STEP3命名行が「範囲＋ファイル名」で識別できる（色のみ状態に依存しない）。
    await expect(page.getByRole('button', { name: '4-7ページ、01_01_002.pdf' })).toBeVisible();

    expect(pageErrors, 'a11yラベル確認で JS 例外が発生しない').toEqual([]);
  });

  test('TC-E2E-D3 出力表のテーブルセマンティクスと操作要素のフォーカス保持', async ({ page }) => {
    // Risk: 出力表が表として読めない／フォーカス退避が操作要素のフォーカスを奪う
    const pageErrors = [];
    page.on('pageerror', (err) => pageErrors.push(`pageerror: ${err.message}`));

    // B3: STEP4出力表が table/columnheader/cell として読める。
    await openDevStep(page, 'output');
    await expect(page.getByRole('table', { name: '出力予定の一覧' })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: '状態' })).toBeVisible();
    await expect(
      page.getByRole('cell', { name: '同名ファイルが既存です。出力先を変更するか既存ファイルを削除してください' })
    ).toBeVisible();

    // B6: STEP2で操作要素（ボタン）をクリックしてもフォーカスは奪われず、ショートカットも効く。
    await openDevStep(page, 'split');
    const fit = page.getByRole('button', { name: '幅合わせ' });
    await fit.click();
    await expect(fit).toBeFocused();
    await page.keyboard.press('ArrowRight');
    await expect.poll(async () => await readCurrentPage(page)).toBe('5');

    expect(pageErrors, '表セマンティクス/フォーカス保持で JS 例外が発生しない').toEqual([]);
  });

  test('TC-E2E-D4 ブランド整理・状態ボタン説明・ショートカット一覧が揃う', async ({ page }) => {
    // Risk: ブランド冗長表記/状態ボタンの用途不明/ショートカット非発見
    const pageErrors = [];
    page.on('pageerror', (err) => pageErrors.push(`pageerror: ${err.message}`));

    await openDevStep(page, 'import');
    // D4: 見出しは「PDF整理ツール」のみ。副ラベルは廃止。
    await expect(page.locator('.brand-row h1')).toHaveText('PDF整理ツール');
    await expect(page.locator('.brand-row .section-label')).toHaveCount(0);
    // E1: 状態ボタンに用途の説明(title)が付く。
    await expect(page.getByRole('button', { name: '状態を復元' })).toHaveAttribute('title', /復元します/);

    // E3: STEP2にショートカット一覧（折りたたみ）がある。
    await openDevStep(page, 'split');
    await expect(page.locator('.shortcut-help summary')).toHaveText('キーボードショートカット');
    await page.locator('.shortcut-help summary').click();
    await expect(page.locator('.shortcut-help')).toContainText('現在ページの前で分割');
    await expect(page.locator('.shortcut-help')).toContainText('プレビューを下 / 上へスクロール');

    expect(pageErrors, 'ブランド整理・ヒント追加で JS 例外が発生しない').toEqual([]);
  });

  test('TC-E2E-D5 ヘッダーサマリは全ステップで撤去され潰れない', async ({ page }) => {
    // Risk: 潰れやすく本文と重複するヘッダーサマリが残り、ヘッダーがごちゃつく
    const pageErrors = [];
    page.on('pageerror', (err) => pageErrors.push(`pageerror: ${err.message}`));

    for (const step of ['import', 'split', 'input', 'output']) {
      await openDevStep(page, step);
      await expect(page.locator('.app-header .header-summary')).toHaveCount(0);
      await expect(page.locator('.app-header.no-summary')).toBeVisible();
    }

    expect(pageErrors, 'ヘッダーサマリ撤去で JS 例外が発生しない').toEqual([]);
  });

  test('TC-E2E-D6 最小幅1200でSTEP2/STEP3の主要操作面が画面内に収まる', async ({ page }) => {
    // Risk: minWidth(=1200)でも左右ペインや操作群が画面外に押し出される
    const pageErrors = [];
    page.on('pageerror', (err) => pageErrors.push(`pageerror: ${err.message}`));
    await page.setViewportSize({ width: 1200, height: 720 });

    await openDevStep(page, 'split');
    await expectNoHorizontalOverflow(page, 'STEP2 1200px');
    await expectInsideViewport(page.locator('.split-list'), 'STEP2 左ペイン');
    await expectInsideViewport(page.locator('.split-work'), 'STEP2 プレビュー');
    await expectInsideViewport(page.getByLabel('STEP2詳細操作'), 'STEP2 右ペイン');
    await expect(page.getByRole('button', { name: '現在ページの前で分割' })).toBeVisible();

    await openDevStep(page, 'input');
    await expectNoHorizontalOverflow(page, 'STEP3 1200px');
    await expectInsideViewport(page.locator('.pane.stack').first(), 'STEP3 セグメント一覧');
    await expectInsideViewport(page.getByLabel('STEP3命名入力'), 'STEP3 命名入力');
    await expect(page.locator('.filename-preview strong')).toBeVisible();

    expect(pageErrors, '最小幅1200確認で JS 例外が発生しない').toEqual([]);
  });

  test('TC-E2E-D7 全体表示はページ全体を枠にフィット（縦も収まる）', async ({ page }) => {
    // Risk: 全体表示(page)が縦をフィットせず、縦長ページが枠から溢れてスクロールが要る
    const pageErrors = [];
    page.on('pageerror', (err) => pageErrors.push(`pageerror: ${err.message}`));
    await page.setViewportSize({ width: 1280, height: 860 });
    await openDevStep(page, 'split');

    const tall = 'data:image/svg+xml;utf8,' + encodeURIComponent(
      "<svg xmlns='http://www.w3.org/2000/svg' width='300' height='1500'><rect width='300' height='1500' fill='%23ddd'/></svg>"
    );
    const measure = async (src) =>
      page.evaluate(async (src) => {
        const img = document.querySelector('.preview-page-layer img');
        img.src = src;
        await img.decode().catch(() => {});
        await new Promise((r) => setTimeout(r, 150));
        const frame = document.querySelector('.preview-frame');
        return { ih: img.getBoundingClientRect().height, fh: frame.clientHeight };
      }, src);

    // 全体表示（dev preview の既定）: 縦長ページでも枠の縦内寸に収まる（フィット）。
    const fit = await measure(tall);
    expect(fit.ih, '全体表示で画像高さが枠の内寸に収まる').toBeLessThanOrEqual(fit.fh + 1);

    // 幅合わせ: 縦長ページは枠の縦を超える（モードが別挙動であることの確認）。
    await page.getByRole('button', { name: '幅合わせ' }).click();
    const widthMode = await measure(tall);
    expect(widthMode.ih, '幅合わせは縦長ページで枠の縦を超える').toBeGreaterThan(widthMode.fh);

    // STEP3(入力)も STEP2 と同じ全体表示フィットであること（input 専用の上書きで
    // 挙動が食い違う退行を防ぐ）。
    await openDevStep(page, 'input');
    const inputFit = await measure(tall);
    expect(inputFit.ih, 'STEP3 の全体表示でも画像高さが枠の内寸に収まる').toBeLessThanOrEqual(inputFit.fh + 1);

    expect(pageErrors, '全体表示フィット確認で JS 例外が発生しない').toEqual([]);
  });

  test('TC-E2E-D8 セグメント除外で出力対象から外れ連番が詰まる', async ({ page }) => {
    // Risk: 白紙等の不要セグメントを除外できず、または除外しても連番が飛ぶ
    const pageErrors = [];
    page.on('pageerror', (err) => pageErrors.push(`pageerror: ${err.message}`));
    await openDevStep(page, 'input');

    const row47 = page.locator('.mini-row').filter({ hasText: '4-7' });
    const row811 = page.locator('.mini-row').filter({ hasText: '8-11' });
    // 初期: 3件・8-11 は 003。
    await expect(row811).toContainText('01_01_003.pdf');

    // 中間(4-7)を出力から除外。
    await page.getByRole('button', { name: '4-7ページを出力から除外' }).click();

    // 4-7 は除外表示／8-11 の連番は 002 に詰まる（番号が飛ばない）。
    await expect(row47).toContainText('除外');
    await expect(row47).toContainText('（出力しない）');
    await expect(row811).toContainText('01_01_002.pdf');
    await expect(page.getByText('1件 除外')).toBeVisible();

    // 復帰すると 8-11 は 003 に戻る。
    await page.getByRole('button', { name: '4-7ページを出力に戻す' }).click();
    await expect(row811).toContainText('01_01_003.pdf');

    expect(pageErrors, 'セグメント除外で JS 例外が発生しない').toEqual([]);
  });

  test('TC-E2E-D10 STEP1 の主CTAは状態で1つに絞られる', async ({ page }) => {
    // Risk: 「PDF選択」と「分割へ進む」が両方 primary(緑)で視線が割れる
    await openDevStep(page, 'import');

    // PDF 読込済み: 主CTAは「分割へ進む」だけが primary、追加ボタンは副次。
    const proceed = page.locator('.import-work button.primary');
    await expect(proceed).toHaveCount(1);
    await expect(proceed).toContainText('分割へ進む');
    await expect(page.locator('.import-work .import-actions button').first()).not.toHaveClass(/primary/);
    await expect(page.locator('.import-work .import-actions button').first()).toContainText('PDFを選択');
  });

  test('TC-E2E-D11 STEP4 で既存衝突があれば上書きして出力できるチェックボックスが出る', async ({ page }) => {
    // Risk: 同名既存ファイルの解消手段が「出力先変更/手動削除」しかなく動線が長い
    await openDevStep(page, 'output');

    // 既存衝突(devサンプルに1件)があるので上書きトグルが表示され、既定はオフ。
    const toggle = page.locator('.overwrite-toggle');
    await expect(toggle).toBeVisible();
    await expect(toggle).toContainText('上書きして出力');
    const checkbox = toggle.locator('input[type="checkbox"]');
    await expect(checkbox).not.toBeChecked();
  });

  test('TC-E2E-D12 STEP3 で命名欄から Enter を押すと次のセグメントへ移動する', async ({ page }) => {
    // Risk: 大量処理で「一覧クリック→入力→一覧クリック」のマウス往復が積み上がる
    await openDevStep(page, 'input');

    // 先頭セグメントを選択し、出力名プレビューを記録。
    await page.locator('.mini-row').first().click();
    const preview = page.locator('.filename-preview strong');
    const before = (await preview.textContent())?.trim() ?? '';
    expect(before.length).toBeGreaterThan(0);

    // 命名欄(箱No)で Enter → 次セグメントへ。出力名プレビューが変わる。
    await page.locator('input[name="box_no"]').focus();
    await page.keyboard.press('Enter');
    await expect(preview).not.toHaveText(before);
  });

  test('TC-E2E-D12-IME IME変換確定中のEnterでは次セグメントへ移動しない', async ({ page }) => {
    await openDevStep(page, 'input');

    await page.locator('.mini-row').first().click();
    const selectedRow = page.locator('.mini-row.selected');
    await expect(selectedRow).toContainText('1-3');

    const boxInput = page.locator('input[name="box_no"]');
    await boxInput.focus();
    await boxInput.dispatchEvent('keydown', {
      bubbles: true,
      cancelable: true,
      isComposing: true,
      key: 'Enter',
      keyCode: 229,
    });

    await expect(selectedRow).toContainText('1-3');
  });

  test('TC-E2E-D13 STEP2 で N ページごとに一括分割できる', async ({ page }) => {
    // Risk: 定型ページ数の書類を1件ずつ手で分割するのは時間の無駄
    await openDevStep(page, 'split');

    // dev は 11ページ。3ページごと → 分割点 4,7,10 → 4書類。
    await page.locator('input[name="interval_pages"]').fill('3');
    await page.getByRole('button', { name: 'このページ数で分割' }).click();
    await expect(page.locator('.status-pill')).toContainText('3ページごとに分割しました');

    // STEP3 でセグメント数が 4 になっていることを確認。
    await page.getByRole('button', { name: '入力へ進む' }).click();
    await expect(page.locator('.mini-row')).toHaveCount(4);
  });

  test('TC-E2E-D14 STEP3 連番の重複・欠番を出力前に警告する', async ({ page }) => {
    // Risk: 手動で連番を取り違えると倉庫採番が破綻するが出力まで気づけない
    await openDevStep(page, 'input');

    // 既定(同一箱・バインダーで 1,2,3)は連番が整っているので警告なし。
    await expect(page.locator('.seq-integrity-warning')).toHaveCount(0);

    // 2番目(4-7・連番2)を 1 に変える → 1 が重複し 2 が欠番になる。
    await page.locator('.mini-row').nth(1).click();
    await page.locator('input[name="seq"]').fill('1');

    const warning = page.locator('.seq-integrity-warning');
    await expect(warning).toBeVisible();
    await expect(warning).toContainText('重複');
    await expect(warning).toContainText('欠番');
  });

  test('TC-E2E-D15 STEP2 補助ツールは既定で畳まれ完了操作まで画面内に収まる', async ({ page }) => {
    // Risk: 右パネルが長すぎてデフォルトサイズで「入力へ進む」等が見切れる
    await openDevStep(page, 'split');

    // 検索・候補・白紙は「検索・補助ツール」アコーディオンに既定で畳まれている。
    await expect(page.locator('.assist-accordion')).toHaveCount(1);
    await expect(page.getByRole('button', { name: '用語を選択' })).not.toBeVisible();

    // 核となる「入力へ進む」がスクロールせず画面内に表示される。
    await expect(page.getByRole('button', { name: '入力へ進む' })).toBeInViewport();
  });
});

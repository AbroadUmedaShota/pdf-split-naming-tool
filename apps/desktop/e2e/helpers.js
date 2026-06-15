// dev preview モード共通ヘルパ。
// app/page.tsx の shouldUseDevPreviewMode() は「非Tauri ＆ localhost ＆ NODE_ENV=development（または ?dev=/?review=step2）」で
// サイドカー（invoke）を呼ばずにサンプル状態の本番想定 UI を描画する。
// dev preview のステップ ID: import / split / input / output（?dev=<stepId>）。

export const DEV_STEPS = ['import', 'split', 'input', 'output'];

/**
 * 指定 dev preview ステップを開き、安定描画を待つ。
 * @param {import('@playwright/test').Page} page
 * @param {'import'|'split'|'input'|'output'} step
 */
export async function openDevStep(page, step) {
  await page.goto(`/?dev=${step}`, { waitUntil: 'networkidle' });
  // dev preview の初期化（applyDevPreviewState）でステータスがサンプル文言になるのを待つ。
  await page
    .locator('[role="status"]', { hasText: 'DEVプレビュー' })
    .first()
    .waitFor({ state: 'visible' });
  // 現在ステップのステッパータブが aria-current=step になることを確認して同期待ち。
  await page.locator(`[data-testid="step-${step}"][aria-current="step"]`).waitFor({ state: 'attached' });
}

/**
 * 現在表示中の検索ハイライト矩形数を数える。
 * dev preview のハイライト矩形は app/page.tsx で `.search-highlight-rect`（コンテナは `.search-highlight-layer`）
 * として描画される。専用クラスのみを対象にし、無関係な SVG やアイコンを誤カウントしない。
 * @param {import('@playwright/test').Page} page
 */
export async function countSearchHighlights(page) {
  return page.evaluate(() => {
    const rects = document.querySelectorAll('.search-highlight-rect').length;
    const layers = document.querySelectorAll('.search-highlight-layer').length;
    return { rects, layers, total: rects + layers };
  });
}

/**
 * 現在ページ番号（プレビュー操作のページ番号入力値）を取得する。
 * @param {import('@playwright/test').Page} page
 * @returns {Promise<string|null>}
 */
export async function readCurrentPage(page) {
  return page.evaluate(() => {
    const input = document.querySelector('input[aria-label="ページ番号"]');
    return input ? input.value : null;
  });
}

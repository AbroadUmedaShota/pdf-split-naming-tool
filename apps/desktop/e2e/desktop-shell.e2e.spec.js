import { test, expect } from '@playwright/test';
import { openDevStep, countSearchHighlights, readCurrentPage } from './helpers.js';

// 対象: apps/desktop（Next.js）http://localhost:3000 を dev preview モード（?dev=<stepId>）で検証する。
// dev preview は Tauri/Python サイドカー無しでサンプル状態の本番想定 UI を描画する（app/page.tsx shouldUseDevPreviewMode）。
//
// 自動化方針:
//   - dev preview で「決定論的に再現できる UI 観点」のみ自動化する。
//   - 処理中状態の注入・旧応答破棄・部分失敗 summary 注入・確認ダイアログ発火・リクエストゲート・
//     再採番/affix 編集の動的動作・ステップ遷移ガード（dev preview ではバイパスされる）は dev preview の
//     静的 early-return 設計で再現できないため、本ファイルでは自動化せず未実装テストケースへ退避する。
//   - 自動化したのは TC-E2E-011（検索ハイライトのページ移動後残留なし・NF-U5）のみ。
//     dev preview のページ移動（selectPageForPreview→clearSearchHighlights）は実コードパスで動作するため、
//     期待結果「前ページのハイライトが残らない」を実 DOM で判定できる。

test.describe('PDF分割くん デスクトップ UI（dev preview）', () => {
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

import { defineConfig, devices } from '@playwright/test';
import { fileURLToPath } from 'node:url';
import { dirname } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));

// E2E は Tauri/Python サイドカー無しで動かすため、STEP1 ハーネス（?e2e=step1）と
// dev preview モード（?dev=<stepId>）を使う。baseURL=http://localhost:3000、chromium のみ。
export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  expect: { timeout: 5_000 },
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: [
    ['list'],
    ['json', { outputFile: 'e2e/.report/results.json' }],
  ],
  use: {
    baseURL: 'http://localhost:3000',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
  // dev server をテスト前に自動起動し、テスト後に自動停止する。
  // 既存の dev server がポート 3000 で稼働していれば再利用する（reuseExistingServer）。
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:3000',
    cwd: __dirname,
    reuseExistingServer: !process.env.CI,
    timeout: 240_000,
    stdout: 'pipe',
    stderr: 'pipe',
  },
});

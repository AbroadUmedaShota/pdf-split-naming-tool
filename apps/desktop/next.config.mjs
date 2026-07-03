import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
// バージョンは package.json を単一ソースにし、ビルド時に NEXT_PUBLIC_APP_VERSION へ注入する。
// Tauri 実行時は getVersion() が正となり、ブラウザプレビュー等のフォールバック表示にこの値を使う。
const packageVersion = JSON.parse(
  readFileSync(join(__dirname, 'package.json'), 'utf8')
).version;

/** @type {import('next').NextConfig} */
const nextConfig = {
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  output: 'export',
  images: {
    unoptimized: true
  },
  env: {
    NEXT_PUBLIC_APP_VERSION: packageVersion
  }
};

export default nextConfig;

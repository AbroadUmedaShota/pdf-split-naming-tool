# Tauri デスクトップ版リリース手順

このアプリのアップデート確認機能は、Tauri v2 updater と GitHub Releases の
`latest.json` を使います。アプリに GitHub token は同梱しません。

## 前提

- `AbroadUmedaShota/pdf-split-naming-tool` は、更新ファイルを認証なしで取得できる公開リポジトリにします。
- ソース公開を避ける場合は、公開リポジトリには Release asset のみ置き、開発リポジトリとは分けます。
- Windows x86_64 を主対象にします。

## 初回だけ行う作業

署名鍵を生成します。private key は repo に入れず、紛失しない場所に保管します。

```powershell
cd apps\desktop
npm run tauri signer generate -- --ci -w "$env:USERPROFILE\.tauri\pdf-organizer.key"
```

表示された public key を `src-tauri/tauri.conf.json` の
`plugins.updater.pubkey` へ設定します。private key は
`%USERPROFILE%\.tauri\pdf-organizer.key` に保存し、Git管理対象へ入れません。

GitHub Actions でビルドする場合だけ、private key の内容を
`TAURI_SIGNING_PRIVATE_KEY`、必要ならパスワードを
`TAURI_SIGNING_PRIVATE_KEY_PASSWORD` として GitHub secret に保存します。

## リリースごとに行う作業

### 資産チェックの役割分担（CI とローカルで別スクリプト）

生成物の検証は2本に分かれています。何を検証するかで使い分けます。

- `check-bundle-assets.mjs`（`release:check-bundle`）— **CI 用**。`.github/workflows/release.yml` から呼ばれ、`build:bundle` が生成する成果物、つまり PyInstaller 製 sidecar exe（`src-tauri/resources/sidecar/pdf-splitter-sidecar.exe`）と Next.js の静的エクスポート（`out/`）だけを検証します。`build:bundle` は `tauri build` も署名も `latest.json` 生成も行わないため、installer・`.sig`・`latest.json` はここでは検証しません。`workflow_dispatch` でタグを打つ前のリハーサル実行にも使えます。
- `check-release-assets.mjs`（`release:check`）— **ローカル用**。下記手順5（`tauri build` と `release:manifest` の実行後）で使い、`src-tauri\target\release\bundle\release-assets` にある NSIS installer・`.sig`・`latest.json` の3点セットと、manifest 内の version・署名・URL の整合まで検証します。`tauri build` を実行しない CI では成立しないため、CI からは呼びません。

まとめると、CI は「バンドルの材料が揃っているか」まで、installer・署名・manifest の検証はローカルの手順5が受け持ちます。

1. `package.json`、`src-tauri/tauri.conf.json`、`src-tauri/Cargo.toml`、
   `..\..\recovery\pyproject.toml`、
   `..\..\recovery\pdf_splitter_tool\app_metadata.py` の version を同じ SemVer に揃えます。
2. 依存関係とテストを確認します。

```powershell
cd apps\desktop
npm run typecheck
npm run build:bundle
cd src-tauri
cargo test
```

3. 署名用 private key を環境変数に設定して Tauri build を実行します。

```powershell
cd apps\desktop
$env:TAURI_SIGNING_PRIVATE_KEY=Get-Content -Raw "$env:USERPROFILE\.tauri\pdf-organizer.key"
$env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD=""
npm run tauri build
$env:TAURI_SIGNING_PRIVATE_KEY=$null
$env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD=$null
```

4. `src-tauri\target\release\bundle\` 配下に生成された Windows installer、
   updater artifact、`.sig` を確認します。
5. GitHub Releases 用の `latest.json` を生成します。
   `release:manifest` は `release-assets` を現行バージョンの3ファイルだけで再生成します。

```powershell
cd apps\desktop
npm run release:manifest
npm run release:check
```

6. PR を `main` へ取り込み、公開承認後に Git tag と GitHub Release を作成します。
   既に tag / Release がある場合は作成をスキップし、asset の差し替えだけ行います。

```powershell
$repo = "AbroadUmedaShota/pdf-split-naming-tool"
$version = "0.1.5"
$tag = "v$version"

gh release create $tag `
  --repo $repo `
  --target main `
  --title "PDF整理ツール $tag" `
  --notes "PDF整理ツール $version"
```

7. GitHub Releases に installer、`.sig`、`latest.json` をアップロードします。
   アップロードには `src-tauri\target\release\bundle\release-assets\` 配下の ASCII 名ファイルを使います。
   installer と `.sig` はそのままアップロードします。

```powershell
$repo = "AbroadUmedaShota/pdf-split-naming-tool"
$version = "0.1.5"
$tag = "v$version"

gh release upload $tag `
  "src-tauri\target\release\bundle\release-assets\pdf-organizer-desktop_${version}_x64-setup.exe" `
  "src-tauri\target\release\bundle\release-assets\pdf-organizer-desktop_${version}_x64-setup.exe.sig" `
  --repo $repo `
  --clobber
```

`latest.json` は GitHub の `releases/latest/download/latest.json` 経路で
`504 Gateway Time-out` になることがあるため、拡張子なしの一時名でアップロードしてから
asset 名だけを `latest.json` に戻します。これにより GitHub Releases 側の content type が
`application/octet-stream` になり、Tauri updater から安定して取得できます。

```powershell
$repo = "AbroadUmedaShota/pdf-split-naming-tool"
$version = "0.1.5"
$tag = "v$version"
$tempDir = Join-Path $env:TEMP "pdf-updater-release"
$tempAsset = Join-Path $tempDir "latest-json"
New-Item -ItemType Directory -Force -Path $tempDir | Out-Null
Copy-Item -LiteralPath "src-tauri\target\release\bundle\release-assets\latest.json" -Destination $tempAsset -Force

gh release upload $tag $tempAsset --repo $repo --clobber
$asset = gh release view $tag --repo $repo --json assets |
  ConvertFrom-Json |
  Select-Object -ExpandProperty assets |
  Where-Object { $_.name -eq "latest-json" } |
  Select-Object -First 1
$assetId = [regex]::Match($asset.apiUrl, "/assets/(\d+)$").Groups[1].Value
gh api -X PATCH "repos/$repo/releases/assets/$assetId" -f name="latest.json" | Out-Null
```

`latest.json` は GitHub Releases の asset として、次の URL で取得できる名前にします。

```text
https://github.com/AbroadUmedaShota/pdf-split-naming-tool/releases/latest/download/latest.json
```

8. 公開後に配信 URL と manifest の中身を確認します。

```powershell
$repo = "AbroadUmedaShota/pdf-split-naming-tool"
$version = "0.1.5"
$tag = "v$version"

curl.exe -sS -L "https://github.com/AbroadUmedaShota/pdf-split-naming-tool/releases/latest/download/latest.json"
curl.exe -I -L "https://github.com/AbroadUmedaShota/pdf-split-naming-tool/releases/latest/download/pdf-organizer-desktop_${version}_x64-setup.exe"
gh release view $tag --repo $repo --json assets,tagName,url
```

`latest.json` asset の `contentType` は `application/octet-stream` であることを確認します。

## 動作確認

通常のリリース確認では、旧版から新版への更新を自動スモークで一気通しします。

```powershell
cd apps\desktop
npm run test:installed-updater
```

既定ではローカルの v0.1.3 installer を入れ直し、GitHub Release 上の v0.1.4 を検出、
`インストール`、再起動後のバージョン表示、同じバージョンでの `最新版です。` 表示まで確認します。
旧版/新版を変える場合は、次の環境変数を指定します。

```powershell
$env:PDF_ORGANIZER_UPDATER_OLD_INSTALLER_PATH="C:\path\to\PDF整理ツール_0.1.3_x64-setup.exe"
$env:PDF_ORGANIZER_UPDATER_OLD_VERSION="0.1.3"
$env:PDF_ORGANIZER_UPDATER_NEW_VERSION="0.1.4"
npm run test:installed-updater
```

手動で確認する場合も、同じ観点で確認します。

- 古いバージョンの packaged app を起動し、ヘッダーの `更新確認` を押します。
- 新しいバージョンが表示されることを確認します。
- `インストール` を押し、Windows installer が更新を完了できることを確認します。
- 再起動後にバージョン表示が新バージョンになることを確認します。
- 同じバージョンでは `最新版です。` と表示されることを確認します。

リリース asset の URL 確認だけでは、アプリ内 updater の E2E 確認は完了扱いにしません。
最低 1 回は旧バージョンをインストールした状態から、新バージョンの検出、インストール、
再起動後のバージョン表示まで確認します。

2026-06-18 の v0.1.4 公開確認では、`npm run test:installed-updater` により
v0.1.3 から v0.1.4 への更新、再起動後の `現在のバージョン: 0.1.4`、
再確認時の `最新版です。` 表示まで成功しています。

> 各リリースで更新スモークの旧→新バージョンは変わります。例えば 0.1.5 の確認では
> 旧 0.1.4 / 新 0.1.5 を、上記「動作確認」の環境変数（`PDF_ORGANIZER_UPDATER_OLD_*` /
> `_NEW_VERSION`）で指定して実行します。

## インストーラ形式（正本）

配布する Windows インストーラは **NSIS の `pdf-organizer-desktop_<version>_x64-setup.exe` ただ1つ**で、
これが updater のターゲットでもあります。`tauri.conf.json` の `bundle.targets` は `["nsis"]` に固定しています。

- `check-release-assets` / `create-updater-manifest` / `installed-updater-smoke` はすべて NSIS の
  `_x64-setup.exe` を前提にしています。
- MSI は配布しません。`check-release-assets` は NSIS 以外の `pdf-organizer-desktop_*` 資産を
  stale として拒否します。インストーラ種別を MSI 等へ変えるときは、これら3スクリプトと
  `bundle.targets` を必ず同時に揃えてください（ズレると updater の asset 名が一致せず、
  自動更新がサイレントで失敗します）。

## 段階配信（デスクトップのカナリア相当）

全ユーザーが単一の `latest.json` を参照するため、`latest.json` を差し替えた瞬間に全員が更新対象になります。
不良版の影響範囲を絞るため、次の段階で配信します。

1. GitHub Release を **draft / prerelease** で作成し、この時点では `latest.json` を新版へ差し替えない。
2. 限定の確認者が NSIS installer を手動ダウンロードして実機検証（`installed-*-smoke` 相当・updater 往復）。
3. 問題なければ Release を publish し、`latest.json` を新版へ差し替えて全体配信に移行する。

## ロールバック手順（不良版を配信してしまった場合）

ローカルファイル出力のみで DB マイグレーションが無いため、巻き戻しは Release asset の差し替えだけで完結します。

1. 直前の正常版（例: v0.1.4）の installer・`.sig`・`latest.json` を手元に用意する（過去の Release からも取得可）。
2. `latest.json` を旧版の内容へ戻し、`releases/latest/download/latest.json` の asset を旧版で `--clobber` 上書きする
   （手順7の content-type 回避と同じやり方）。これで updater は旧版を「最新」と認識し、新規の更新適用を止められる。
3. 不良版の Release を draft 化または削除し、`latest` が旧版 Release を指す状態にする。
4. `curl` で `latest.json` の `version` が旧版へ戻ったことを確認する（手順8と同じ）。

所要は手作業で約5〜10分（推定）。**既に不良版へ更新済みのユーザーには、updater は通常ダウングレードしないため、
旧版 installer の手動再インストールを案内する**。

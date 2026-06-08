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

1. `package.json`、`src-tauri/tauri.conf.json`、`src-tauri/Cargo.toml`、
   `..\..\recovery\pdf_splitter_tool\app_metadata.py` の version を同じ SemVer に揃えます。
2. 依存関係とテストを確認します。

```powershell
cd apps\desktop
npm run typecheck
npm run build
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

```powershell
cd apps\desktop
npm run release:manifest
```

6. GitHub Releases に installer、`.sig`、`latest.json` をアップロードします。
   アップロードには `src-tauri\target\release\bundle\release-assets\` 配下の ASCII 名ファイルを使います。
   installer と `.sig` はそのままアップロードします。

```powershell
$repo = "AbroadUmedaShota/pdf-split-naming-tool"
$version = "0.1.1"
$tag = "v$version"

gh release upload $tag `
  "src-tauri\target\release\bundle\release-assets\pdf-organizer-desktop_${version}_x64-setup.exe" `
  "src-tauri\target\release\bundle\release-assets\pdf-organizer-desktop_${version}_x64-setup.exe.sig" `
  --repo $repo
```

`latest.json` は GitHub の `releases/latest/download/latest.json` 経路で
`504 Gateway Time-out` になることがあるため、拡張子なしの一時名でアップロードしてから
asset 名だけを `latest.json` に戻します。これにより GitHub Releases 側の content type が
`application/octet-stream` になり、Tauri updater から安定して取得できます。

```powershell
$repo = "AbroadUmedaShota/pdf-split-naming-tool"
$version = "0.1.1"
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

7. 公開後に配信 URL と manifest の中身を確認します。

```powershell
$repo = "AbroadUmedaShota/pdf-split-naming-tool"
$version = "0.1.1"
$tag = "v$version"

curl.exe -sS -L "https://github.com/AbroadUmedaShota/pdf-split-naming-tool/releases/latest/download/latest.json"
curl.exe -I -L "https://github.com/AbroadUmedaShota/pdf-split-naming-tool/releases/latest/download/pdf-organizer-desktop_${version}_x64-setup.exe"
gh release view $tag --repo $repo --json assets,tagName,url
```

`latest.json` asset の `contentType` は `application/octet-stream` であることを確認します。

## 動作確認

- 古いバージョンの packaged app を起動し、ヘッダーの `更新確認` を押します。
- 新しいバージョンが表示されることを確認します。
- `インストール` を押し、Windows installer が更新を完了できることを確認します。
- 同じバージョンでは `最新版です。` と表示されることを確認します。

リリース asset の URL 確認だけでは、アプリ内 updater の E2E 確認は完了扱いにしません。
最低 1 回は旧バージョンをインストールした状態から、新バージョンの検出、インストール、
再起動後のバージョン表示まで確認します。

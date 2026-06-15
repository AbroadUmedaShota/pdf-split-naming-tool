@echo off
chcp 65001 >nul
title PDF分割くん UIプレビュー（Rust不要）
cd /d "%~dp0apps\desktop"

where npm >nul 2>nul || (echo [エラー] Node.js/npm が見つかりません。 https://nodejs.org からインストールしてください。 & pause & exit /b 1)

if not exist "node_modules" (echo 初回セットアップ: npm install を実行します... & call npm install || (echo [エラー] npm install に失敗しました。 & pause & exit /b 1))

echo UIプレビューを起動します。ブラウザで http://localhost:3000 を開いてください。
echo （Rust不要。ただしフォルダを開く・PDF処理などTauri機能は動きません）
echo 停止するには このウィンドウで Ctrl+C を押してください。
call npm run dev

echo.
echo 終了しました。何かキーを押すと閉じます。
pause >nul

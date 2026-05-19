param(
    [string]$VersionName = "",
    [switch]$SkipTests,
    [switch]$SkipZip
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RecoveryRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$RepoRoot = Resolve-Path (Join-Path $RecoveryRoot "..")

if ([string]::IsNullOrWhiteSpace($VersionName)) {
    $VersionName = "pdf-split-naming-tool-recovery-" + (Get-Date -Format "yyyyMMdd-HHmmss")
}

if ($VersionName -notmatch "^[A-Za-z0-9._-]+$") {
    throw "VersionName can contain only A-Z, a-z, 0-9, dot, underscore, and hyphen: $VersionName"
}

$DistRoot = Join-Path $RecoveryRoot "dist"
$BuildRoot = Join-Path $RecoveryRoot "build\pyinstaller"
$SpecRoot = Join-Path $RecoveryRoot "build\spec"
$TargetDir = Join-Path $DistRoot $VersionName
$ZipPath = Join-Path $DistRoot "$VersionName.zip"
$ChecklistPath = Join-Path $RepoRoot "docs\2026-05-19_配布前チェックリスト.md"

if (Test-Path -LiteralPath $TargetDir) {
    throw "Distribution folder already exists. Choose a new VersionName: $TargetDir"
}
if ((-not $SkipZip) -and (Test-Path -LiteralPath $ZipPath)) {
    throw "Distribution zip already exists. Choose a new VersionName: $ZipPath"
}

New-Item -ItemType Directory -Force -Path $DistRoot, $BuildRoot, $SpecRoot | Out-Null

Push-Location $RecoveryRoot
try {
    & python -m compileall pdf_splitter_tool tests
    if (-not $SkipTests) {
        & python -m pytest
    }

    & python -m PyInstaller `
        --noconfirm `
        --clean `
        --onedir `
        --windowed `
        --name $VersionName `
        --distpath $DistRoot `
        --workpath $BuildRoot `
        --specpath $SpecRoot `
        (Join-Path $RecoveryRoot "pdf_splitter_tool\__main__.py")

    $ExePath = Join-Path $TargetDir "$VersionName.exe"
    if (-not (Test-Path -LiteralPath $ExePath)) {
        throw "Built EXE was not found: $ExePath"
    }

    $SmokePath = Join-Path $TargetDir "smoke-result.json"
    $SmokeProcess = Start-Process `
        -FilePath $ExePath `
        -ArgumentList @("--smoke", "--smoke-output", $SmokePath) `
        -PassThru `
        -WindowStyle Hidden
    if (-not $SmokeProcess.WaitForExit(15000)) {
        Stop-Process -Id $SmokeProcess.Id -Force
        throw "Smoke check did not finish within 15 seconds: $ExePath"
    }
    if ($SmokeProcess.ExitCode -ne 0) {
        throw "Smoke check failed with exit code $($SmokeProcess.ExitCode): $ExePath"
    }
    if (-not (Test-Path -LiteralPath $SmokePath)) {
        throw "Smoke result was not created: $SmokePath"
    }

    Copy-Item -LiteralPath $ChecklistPath -Destination (Join-Path $TargetDir "配布前チェックリスト.md")

    if (-not $SkipZip) {
        Compress-Archive -LiteralPath $TargetDir -DestinationPath $ZipPath
    }

    Write-Host "Distribution folder: $TargetDir"
    if (-not $SkipZip) {
        Write-Host "Distribution zip: $ZipPath"
    }
    Write-Host "Smoke result: $SmokePath"
}
finally {
    Pop-Location
}

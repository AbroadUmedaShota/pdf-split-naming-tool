$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$DesktopRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
$RepoRoot = Resolve-Path (Join-Path $DesktopRoot '..\..')
$RecoveryRoot = Join-Path $RepoRoot 'recovery'
$ResourceDir = Join-Path $DesktopRoot 'src-tauri\resources\sidecar'
$BuildRoot = Join-Path $RecoveryRoot 'build\tauri-sidecar'
$SpecRoot = Join-Path $RecoveryRoot 'build\spec'
$SidecarName = 'pdf-splitter-sidecar'
$SidecarExe = Join-Path $ResourceDir "$SidecarName.exe"
$SmokePath = Join-Path $BuildRoot 'sidecar-smoke-result.json'

New-Item -ItemType Directory -Force -Path $ResourceDir, $BuildRoot, $SpecRoot | Out-Null
Remove-Item -LiteralPath $SidecarExe -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $SmokePath -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath (Join-Path $ResourceDir 'smoke-result.json') -Force -ErrorAction SilentlyContinue

Push-Location $RecoveryRoot
try {
    python -m PyInstaller `
        --noconfirm `
        --clean `
        --onefile `
        --name $SidecarName `
        --distpath $ResourceDir `
        --workpath $BuildRoot `
        --specpath $SpecRoot `
        (Join-Path $RecoveryRoot 'pdf_splitter_tool\__main__.py')

    if (-not (Test-Path -LiteralPath $SidecarExe)) {
        throw "Sidecar executable was not created: $SidecarExe"
    }

    $SmokeProcess = Start-Process `
        -FilePath $SidecarExe `
        -ArgumentList @('--smoke', '--smoke-output', $SmokePath) `
        -PassThru `
        -WindowStyle Hidden
    if (-not $SmokeProcess.WaitForExit(240000)) {
        Stop-Process -Id $SmokeProcess.Id -Force
        throw "Sidecar smoke check timed out: $SidecarExe"
    }
    if ($SmokeProcess.ExitCode -ne 0) {
        throw "Sidecar smoke check failed with exit code $($SmokeProcess.ExitCode): $SidecarExe"
    }
    if (-not (Test-Path -LiteralPath $SmokePath)) {
        throw "Sidecar smoke result was not created: $SmokePath"
    }
}
finally {
    Pop-Location
}

Write-Host "Sidecar executable: $SidecarExe"

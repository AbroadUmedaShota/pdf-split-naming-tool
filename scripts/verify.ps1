$ErrorActionPreference = 'Stop'

function Invoke-VerifyStep {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Label,

        [Parameter(Mandatory = $true)]
        [scriptblock]$Command
    )

    Write-Host ''
    Write-Host "== $Label =="

    & $Command
    $exitCode = $LASTEXITCODE

    if ($exitCode -ne 0) {
        Write-Error "$Label failed with exit code $exitCode."
        exit $exitCode
    }
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$recoveryPath = Join-Path $repoRoot 'recovery'
$recoveryTestsPath = Join-Path $recoveryPath 'tests'
$desktopPath = Join-Path $repoRoot 'apps\desktop'

Invoke-VerifyStep 'Python recovery tests' {
    $originalPythonPathExists = Test-Path Env:PYTHONPATH
    $originalPythonPath = $env:PYTHONPATH

    Push-Location $repoRoot
    try {
        $env:PYTHONPATH = $recoveryPath
        python -m pytest $recoveryTestsPath -q
    }
    finally {
        Pop-Location

        if ($originalPythonPathExists) {
            $env:PYTHONPATH = $originalPythonPath
        }
        else {
            Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
        }
    }
}

Invoke-VerifyStep 'Desktop tests' {
    Push-Location $desktopPath
    try {
        npm run test:desktop
    }
    finally {
        Pop-Location
    }
}

Invoke-VerifyStep 'Desktop typecheck' {
    Push-Location $desktopPath
    try {
        npm run typecheck
    }
    finally {
        Pop-Location
    }
}

Write-Host ''
Write-Host 'Verification completed successfully.'

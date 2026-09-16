param(
    [switch]$InstallInno,
    [switch]$SkipAppBuild
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

function Find-InnoCompiler {
    $command = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $candidates = @(
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
    )
    return $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}

if (-not $SkipAppBuild) {
    & powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

$compiler = Find-InnoCompiler
if (-not $compiler) {
    if ($InstallInno) {
        winget install --id JRSoftware.InnoSetup --exact --silent --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
        $compiler = Find-InnoCompiler
    }

    if (-not $compiler) {
        Write-Host "Inno Setup compiler ISCC.exe is not installed."
        Write-Host "Run: powershell -ExecutionPolicy Bypass -File scripts\build_installer.ps1 -InstallInno"
        exit 2
    }
}

& $compiler "installer\purchase-forecast-service.iss"
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host "Windows installer built: dist\PurchaseForecastServiceSetup.exe"

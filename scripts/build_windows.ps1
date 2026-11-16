param(
    [switch]$InstallPyInstaller,
    [switch]$IncludeLocalOrderHistory
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

$pythonCandidates = @(
    (Join-Path $projectRoot ".venv\Scripts\python.exe"),
    (Join-Path $env:LOCALAPPDATA "Python\pythoncore-3.14-64\python.exe"),
    (Join-Path $env:LOCALAPPDATA "Programs\Python\Python314\python.exe"),
    (Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe"),
    (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe")
)
$PythonExe = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $PythonExe) {
    $PythonExe = "py"
}

function Test-PyInstaller {
    try {
        & $PythonExe -m PyInstaller --version *> $null
        return $LASTEXITCODE -eq 0
    }
    catch {
        return $false
    }
}

if (-not (Test-PyInstaller)) {
    if (-not $InstallPyInstaller) {
        Write-Host "PyInstaller is not installed."
        Write-Host "Run: powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1 -InstallPyInstaller"
        exit 2
    }
    & $PythonExe -m pip install pyinstaller
}

$pyInstallerArgs = @(
    "--noconfirm",
    "--clean",
    "--onefile",
    "--windowed",
    "--name",
    "purchase-forecast-service",
    "--add-data",
    "data\examples;data\examples",
    "--collect-submodules",
    "src",
    "--collect-submodules",
    "scripts"
)

$previousOrdersDir = "Прошлые заказы"
# Python из runtime Codex использует дополнительный публичный файл сертификатов.
# Его нужно переносить вместе с ssl.py; проверку TLS не отключаем.
$sslResourcePath = & $PythonExe -c "import pathlib, ssl; print(pathlib.Path(ssl.__file__).with_name('codex-rejected-cas.pem'))"
if (Test-Path -LiteralPath $sslResourcePath) {
    $pyInstallerArgs += @("--add-data", "$sslResourcePath;.")
}

if ($IncludeLocalOrderHistory -and (Test-Path -LiteralPath $previousOrdersDir)) {
    $pyInstallerArgs += @("--add-data", "$previousOrdersDir;$previousOrdersDir")
}

$pyInstallerArgs += "src\app\windows_launcher.py"

& $PythonExe -m PyInstaller @pyInstallerArgs
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Copy-Item -LiteralPath .env.example -Destination dist\.env.example -Force

Write-Host "Windows app built: dist\purchase-forecast-service.exe"
Write-Host "Launch opens a standalone app window. Setup appears only when Supabase settings are missing."
Write-Host "Saved settings path: %APPDATA%\purchase-forecast-service\.env"
Write-Host "Optional portable override: place .env next to the exe."

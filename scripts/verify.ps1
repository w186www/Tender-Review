param([string]$PythonExecutable = "")
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
if (-not $PythonExecutable) {
    $LocalPython = Join-Path $ProjectRoot ".venv/Scripts/python.exe"
    $PythonExecutable = if (Test-Path $LocalPython) { $LocalPython } else { "python" }
}
$PreviousPythonPath = $env:PYTHONPATH
$PreviousPythonUtf8 = $env:PYTHONUTF8
$PreviousPythonEncoding = $env:PYTHONIOENCODING
$env:PYTHONPATH = (Join-Path $ProjectRoot "src") + [IO.Path]::PathSeparator + $PSScriptRoot
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

function Invoke-Check([string]$Title, [string[]]$Arguments) {
    Write-Host $Title
    & $PythonExecutable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Title failed (exit $LASTEXITCODE)." }
}

Push-Location $ProjectRoot
try {
    Invoke-Check "[1/6] Contracts, examples, State generation and task evidence" @("scripts/verify_repo.py")
    Invoke-Check "Legal contract generation consistency" @("scripts/generate_legal_contracts.py", "--check")
    Invoke-Check "[2/6] Code and static security rules" @("-m", "ruff", "check", "src", "scripts", "tests")
    Invoke-Check "[3/6] Strict application type checking" @("-m", "mypy", "src")
    New-Item -ItemType Directory -Path (Join-Path $ProjectRoot ".verification") -Force | Out-Null
    $TestTempPath = [IO.Path]::GetFullPath((Join-Path $ProjectRoot (".verification/test-" + [guid]::NewGuid().ToString("N"))))
    if (-not $TestTempPath.StartsWith($ProjectRoot + [IO.Path]::DirectorySeparatorChar)) {
        throw "Test temporary directory is outside the project."
    }
    Invoke-Check "[4/6] Contract and regression tests (empty suite fails)" @(
        "-m", "pytest", "--basetemp", $TestTempPath,
        "--junitxml", ".verification/pytest-result.xml", "--tb=short"
    )
    Invoke-Check "[5/6] Real backend startup and loopback HTTP check" @("scripts/smoke_backend.py")
    Invoke-Check "[6/6] Real authenticated backend and project lifecycle" @("scripts/smoke_identity.py")
    Write-Host "PASS: development baseline checks; production acceptance is a separate milestone."
}
finally {
    Pop-Location
    $env:PYTHONPATH = $PreviousPythonPath
    $env:PYTHONUTF8 = $PreviousPythonUtf8
    $env:PYTHONIOENCODING = $PreviousPythonEncoding
}

param(
    [string]$PythonExecutable = "",
    [ValidateSet("Full", "Quick", "Focused")][string]$Mode = "Full",
    [string[]]$TestPaths = @()
)
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$SelectedTests = @()
if ($Mode -eq "Focused") {
    if ($TestPaths.Count -eq 0) { throw "Focused mode requires explicit -TestPaths." }
    foreach ($Item in $TestPaths) {
        if ([IO.Path]::IsPathRooted($Item)) { throw "Test paths must be repository-relative." }
        $Resolved = [IO.Path]::GetFullPath((Join-Path $ProjectRoot $Item))
        $TestsRoot = [IO.Path]::GetFullPath((Join-Path $ProjectRoot "tests"))
        if (-not $Resolved.StartsWith($TestsRoot + [IO.Path]::DirectorySeparatorChar) -or
            -not (Test-Path -LiteralPath $Resolved -PathType Leaf) -or
            [IO.Path]::GetFileName($Resolved) -notmatch '^test_.+\.py$') {
            throw "Focused test selection must name existing test_*.py files inside tests."
        }
        $SelectedTests += $Resolved
    }
}
elseif ($TestPaths.Count -ne 0) { throw "-TestPaths is only valid in Focused mode." }
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

function Invoke-FrontendChecks {
    $FrontendRoot = Join-Path $ProjectRoot "src/frontend"
    $NodeCommand = Get-Command node -ErrorAction SilentlyContinue
    $NpmCommand = Get-Command npm -ErrorAction SilentlyContinue
    if (-not $NodeCommand -or -not $NpmCommand) {
        throw "Frontend checks require Node.js and npm. See docs/development/frontend-workbench.md."
    }
    $NpmVersionText = (& npm --version).Trim()
    if ($LASTEXITCODE -ne 0 -or $NpmVersionText -notmatch '^\d+\.\d+\.\d+') {
        throw "Could not determine the npm version."
    }
    $NpmVersion = [version]$Matches[0]
    if ($NpmVersion.Major -lt 10 -or $NpmVersion.Major -ge 12) {
        throw "Unsupported npm version $NpmVersionText; use npm 10 or 11."
    }

    Push-Location $FrontendRoot
    $PreviousTemp = $env:TEMP
    $PreviousTmp = $env:TMP
    $PreviousTmpDir = $env:TMPDIR
    try {
        Write-Host "[4/7] Frontend contract, static, unit and build checks"
        & node scripts/check_frontend_runtime.mjs
        if ($LASTEXITCODE -ne 0) { throw "Frontend runtime compatibility check failed." }
        if (-not (Test-Path -LiteralPath "node_modules/openapi-fetch/package.json" -PathType Leaf)) {
            Write-Host "Installing locked frontend dependencies with npm ci."
            & npm ci --no-audit --no-fund
            if ($LASTEXITCODE -ne 0) { throw "npm ci failed (exit $LASTEXITCODE)." }
        }

        $FrontendTemp = [IO.Path]::GetFullPath((Join-Path $ProjectRoot ".verification/frontend-tmp"))
        if (-not $FrontendTemp.StartsWith($ProjectRoot + [IO.Path]::DirectorySeparatorChar)) {
            throw "Frontend test temporary directory is outside the project."
        }
        New-Item -ItemType Directory -Path $FrontendTemp -Force | Out-Null
        $env:TEMP = $FrontendTemp
        $env:TMP = $FrontendTemp
        $env:TMPDIR = $FrontendTemp

        $Checks = @(
            @("OpenAPI-generated client matches the contract", "api:check"),
            @("Frontend lint", "lint"),
            @("Frontend TypeScript", "typecheck"),
            @("Frontend unit tests", "test"),
            @("Frontend production build", "build")
        )
        foreach ($Check in $Checks) {
            Write-Host $Check[0]
            & npm run $Check[1]
            if ($LASTEXITCODE -ne 0) { throw "$($Check[0]) failed (exit $LASTEXITCODE)." }
        }
        Write-Host "Browser E2E is a separate required acceptance check; see docs/development/TASK-0011-validation.md for its isolated backend prerequisites and current status."
    }
    finally {
        Pop-Location
        $env:TEMP = $PreviousTemp
        $env:TMP = $PreviousTmp
        $env:TMPDIR = $PreviousTmpDir
    }
}

Push-Location $ProjectRoot
try {
    Invoke-Check "[1/7] Contracts, examples, State generation and task evidence" @("scripts/verify_repo.py")
    Invoke-Check "Legal contract generation consistency" @("scripts/generate_legal_contracts.py", "--check")
    Invoke-Check "Ingestion contract generation consistency" @("scripts/generate_ingestion_contracts.py", "--check")
    Invoke-Check "Rule/Skill contract generation consistency" @("scripts/generate_rule_contracts.py", "--check")
    if ($Mode -eq "Quick") {
        Write-Host "PASS: Quick repository/contract/secret checks only; no runtime tests or startup checks executed."
        return
    }
    Invoke-Check "[2/7] Code and static security rules" @("-m", "ruff", "check", "src", "scripts", "tests")
    Invoke-Check "[3/7] Strict application type checking" @("-m", "mypy", "src")
    Invoke-FrontendChecks
    New-Item -ItemType Directory -Path (Join-Path $ProjectRoot ".verification") -Force | Out-Null
    $TestTempPath = [IO.Path]::GetFullPath((Join-Path $ProjectRoot (".verification/test-" + [guid]::NewGuid().ToString("N"))))
    if (-not $TestTempPath.StartsWith($ProjectRoot + [IO.Path]::DirectorySeparatorChar)) {
        throw "Test temporary directory is outside the project."
    }
    $ResultFile = if ($Mode -eq "Full") { ".verification/pytest-result.xml" } else { ".verification/pytest-focused-result.xml" }
    $TestArguments = @("-m", "pytest", "--basetemp", $TestTempPath,
        "--junitxml", $ResultFile, "--tb=short")
    if ($Mode -eq "Focused") { $TestArguments += $SelectedTests }
    Invoke-Check "[5/7] $Mode backend regression tests (empty suite fails)" $TestArguments
    if ($Mode -eq "Focused") {
        Write-Host "PASS: Focused checks for explicitly selected files only; not full acceptance or startup evidence."
        return
    }
    Invoke-Check "[6/7] Real backend startup and loopback HTTP check" @("scripts/smoke_backend.py")
    Invoke-Check "[7/7] Real authenticated backend and project lifecycle" @("scripts/smoke_identity.py")
    Write-Host "PASS: development baseline checks; production acceptance is a separate milestone."
}
finally {
    Pop-Location
    $env:PYTHONPATH = $PreviousPythonPath
    $env:PYTHONUTF8 = $PreviousPythonUtf8
    $env:PYTHONIOENCODING = $PreviousPythonEncoding
}

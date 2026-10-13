param(
    [string]$HostAddress = "",
    [int]$Port = 0,
    [string]$PythonExecutable = ""
)
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
if (-not $PythonExecutable) {
    $LocalPython = Join-Path $ProjectRoot ".venv/Scripts/python.exe"
    $PythonExecutable = if (Test-Path $LocalPython) { $LocalPython } else { "python" }
}
$PreviousPythonUtf8 = $env:PYTHONUTF8
$PreviousPythonPath = $env:PYTHONPATH
$env:PYTHONUTF8 = "1"
$env:PYTHONPATH = Join-Path $ProjectRoot "src"
$StartArguments = @("-m", "bidding_compliance.api")
if ($HostAddress) { $StartArguments += @("--host", $HostAddress) }
if ($Port -ne 0) { $StartArguments += @("--port", $Port.ToString()) }
Push-Location $ProjectRoot
try {
    & $PythonExecutable @StartArguments
    if ($LASTEXITCODE -ne 0) { throw "Backend failed (exit $LASTEXITCODE)." }
}
finally {
    Pop-Location
    $env:PYTHONUTF8 = $PreviousPythonUtf8
    $env:PYTHONPATH = $PreviousPythonPath
}

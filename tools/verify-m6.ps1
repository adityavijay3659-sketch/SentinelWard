[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Python,
    [Parameter(Mandatory = $true)][string]$ArtifactRoot,
    [string]$VitalDbRoot = $env:SENTINEL_TEST_VITALDB_ROOT,
    [string]$DatabaseUrl = $env:SENTINEL_TEST_DATABASE_URL,
    [switch]$UnitOnly
)
$ErrorActionPreference = 'Stop'
$repo = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$artifact = [System.IO.Path]::GetFullPath($ArtifactRoot)
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw 'Python executable unavailable' }
if (Test-Path -LiteralPath $artifact) { throw 'Use a new artifact directory; previous results are preserved' }
if (-not $UnitOnly) {
    if (-not $DatabaseUrl) { throw 'Full verification requires an isolated test database URL' }
    $databaseUri = [uri]$DatabaseUrl
    if ($databaseUri.Host -notin @('127.0.0.1', 'localhost', '::1') -or
        $databaseUri.AbsolutePath -notmatch '^/sentinel_m6_[a-z0-9_]+$') {
        throw 'Full verification requires a loopback database named sentinel_m6_*'
    }
    if (-not (Test-Path -LiteralPath (Join-Path $VitalDbRoot 'selection.json') -PathType Leaf)) {
        throw 'Full verification requires the existing VitalDB cohort'
    }
}
$variables = @('PYTHONPATH', 'PYTHONDONTWRITEBYTECODE', 'TEMP', 'TMP', 'MYPY_CACHE_DIR',
    'SENTINEL_TEST_DATABASE_URL', 'SENTINEL_TEST_VITALDB_ROOT', 'LANGGRAPH_STRICT_MSGPACK')
$previous = @{}
foreach ($name in $variables) { $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
$previousLocation = Get-Location
try {
    New-Item -ItemType Directory -Path $artifact | Out-Null
    $env:PYTHONPATH = (Join-Path $repo 'src') + [IO.Path]::PathSeparator + $repo
    $env:PYTHONDONTWRITEBYTECODE = '1'
    $env:TEMP = $artifact
    $env:TMP = $artifact
    $env:MYPY_CACHE_DIR = Join-Path $artifact 'mypy-cache'
    $env:LANGGRAPH_STRICT_MSGPACK = 'true'
    $env:SENTINEL_TEST_DATABASE_URL = if ($UnitOnly) { $null } else { $DatabaseUrl }
    $env:SENTINEL_TEST_VITALDB_ROOT = if ($UnitOnly) { $null } else { $VitalDbRoot }
    Set-Location -LiteralPath $repo
    & $Python -B -m ruff check . --no-cache
    if ($LASTEXITCODE -ne 0) { throw 'Lint failed' }
    & $Python -B -m ruff format --check . --no-cache
    if ($LASTEXITCODE -ne 0) { throw 'Format check failed' }
    & $Python -B -m mypy
    if ($LASTEXITCODE -ne 0) { throw 'Type check failed' }
    $testArguments = @('-B', '-m', 'pytest', '-q', '-p', 'no:cacheprovider',
        '--basetemp', (Join-Path $artifact 'pytest-temp'),
        '--junitxml', (Join-Path $artifact 'tests.xml'))
    if ($UnitOnly) { $testArguments += @('-m', 'not integration') }
    & $Python @testArguments
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
    [xml]$junit = Get-Content -LiteralPath (Join-Path $artifact 'tests.xml') -Raw
    $suites = @($junit.testsuites.testsuite)
    $skipped = ($suites | Measure-Object -Property skipped -Sum).Sum
    if (-not $UnitOnly -and $skipped -gt 0) { throw 'Full verification contains skipped tests' }
    $mode = if ($UnitOnly) { 'UNIT ONLY; INTEGRATIONS PENDING' } else { 'FULL LOCAL SUITE' }
    Write-Output "M6 VERIFY | $mode | PASSED | RESEARCH ONLY"
} finally {
    Set-Location -LiteralPath $previousLocation.Path
    foreach ($name in $variables) { [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process') }
}

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)]
    [string]$SourceDirectory,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^JPPM[0-9]+$')]
    [string]$ReleaseId,

    [ValidateSet('codex', 'claude', 'both')]
    [string]$Client = 'both',

    [string]$Database,

    [string]$KitOutput,

    [switch]$RegisterClients
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,

        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE`: $FilePath"
    }
}

$repositoryRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$sourcePath = (Resolve-Path -LiteralPath $SourceDirectory).Path
if (-not (Test-Path -LiteralPath $sourcePath -PathType Container)) {
    throw "PMGS source directory is not a directory: $sourcePath"
}

if ([string]::IsNullOrWhiteSpace($Database)) {
    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        throw 'LOCALAPPDATA is unavailable. Pass -Database explicitly.'
    }
    $Database = Join-Path $env:LOCALAPPDATA 'pmgs-reference\data\current.sqlite'
}
if ([string]::IsNullOrWhiteSpace($KitOutput)) {
    $KitOutput = Join-Path $repositoryRoot 'build\local-agent-kit'
}

$databasePath = [System.IO.Path]::GetFullPath($Database)
$kitPath = [System.IO.Path]::GetFullPath($KitOutput)
if (Test-Path -LiteralPath $databasePath) {
    throw "Database already exists. Choose a new path or move the existing file: $databasePath"
}
if (Test-Path -LiteralPath $kitPath) {
    throw "Agent kit output already exists. Choose a new path: $kitPath"
}

$uv = Get-Command uv -ErrorAction Stop
if ($RegisterClients) {
    $requiredClients = if ($Client -eq 'both') { @('codex', 'claude') } else { @($Client) }
    foreach ($requiredClient in $requiredClients) {
        if ($null -eq (Get-Command $requiredClient -ErrorAction SilentlyContinue)) {
            throw "Requested client command is unavailable: $requiredClient"
        }
    }
}

if (-not $PSCmdlet.ShouldProcess($databasePath, 'Build and configure the local PMGS agent kit')) {
    return
}

Push-Location $repositoryRoot
try {
    Invoke-CheckedCommand -FilePath $uv.Source -Arguments @(
        'sync', '--frozen', '--all-groups'
    )

    $pythonExecutable = Join-Path $repositoryRoot '.venv\Scripts\python.exe'
    $venvConfig = Join-Path $repositoryRoot '.venv\pyvenv.cfg'
    if (-not (Test-Path -LiteralPath $pythonExecutable -PathType Leaf)) {
        throw "Stable virtual-environment interpreter was not created: $pythonExecutable"
    }
    if (-not (Test-Path -LiteralPath $venvConfig -PathType Leaf)) {
        throw "Virtual-environment configuration is missing: $venvConfig"
    }
    $signature = Get-AuthenticodeSignature -LiteralPath $pythonExecutable
    if ($signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid) {
        throw "Virtual-environment Python signature is not valid: $($signature.Status)"
    }

    $databaseParent = Split-Path -Parent $databasePath
    [void](New-Item -ItemType Directory -Force -Path $databaseParent)
    $reportRoot = Join-Path $repositoryRoot "build\local-agent-$ReleaseId"
    [void](New-Item -ItemType Directory -Force -Path $reportRoot)
    $manifestPath = Join-Path $reportRoot 'source-manifest.jsonl'
    $summaryPath = Join-Path $reportRoot 'inventory-summary.json'
    $buildReport = Join-Path $reportRoot 'build-report.json'
    $validationReport = Join-Path $reportRoot 'validation-report.json'

    Invoke-CheckedCommand -FilePath $pythonExecutable -Arguments @(
        '-m', 'pmgs_reference.cli', 'inventory', $sourcePath,
        '--output', $manifestPath, '--summary', $summaryPath
    )
    Invoke-CheckedCommand -FilePath $pythonExecutable -Arguments @(
        '-m', 'pmgs_reference.cli', 'build', $sourcePath,
        '--release', $ReleaseId, '--output', $databasePath, '--report', $buildReport
    )
    Invoke-CheckedCommand -FilePath $pythonExecutable -Arguments @(
        '-m', 'pmgs_reference.cli', 'validate', $databasePath,
        '--report', $validationReport
    )
    Invoke-CheckedCommand -FilePath $pythonExecutable -Arguments @(
        '-m', 'pmgs_reference.cli', 'doctor', '--db', $databasePath,
        '--python-executable', $pythonExecutable, '--json'
    )
    Invoke-CheckedCommand -FilePath $pythonExecutable -Arguments @(
        '-m', 'pmgs_reference.cli', 'agent-kit', '--db', $databasePath,
        '--output', $kitPath, '--python-executable', $pythonExecutable,
        '--client', $Client
    )
    Invoke-CheckedCommand -FilePath $pythonExecutable -Arguments @(
        '-m', 'pmgs_reference.cli', 'install-agent-skill', '--client', $Client
    )

    if ($RegisterClients) {
        $serverArguments = @(
            $pythonExecutable, '-m', 'pmgs_reference.cli', 'mcp', '--db', $databasePath
        )
        if ($Client -in @('codex', 'both')) {
            $codexArguments = @(
                'mcp', 'add', 'pmgs-reference', '--'
            ) + $serverArguments
            Invoke-CheckedCommand -FilePath 'codex' -Arguments $codexArguments
        }
        if ($Client -in @('claude', 'both')) {
            $claudeArguments = @(
                'mcp', 'add', '--transport', 'stdio', '--scope', 'user',
                'pmgs-reference', '--'
            ) + $serverArguments
            Invoke-CheckedCommand -FilePath 'claude' -Arguments $claudeArguments
        }
    }
}
finally {
    Pop-Location
}

[pscustomobject]@{
    Database          = $databasePath
    AgentKit          = $kitPath
    Client            = $Client
    ClientsRegistered = [bool]$RegisterClients
} | ConvertTo-Json

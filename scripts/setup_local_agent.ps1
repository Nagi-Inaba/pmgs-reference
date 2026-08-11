[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)]
    [string]$SourceDirectory,

    [ValidatePattern('^JPPM[0-9]+$')]
    [string]$ReleaseId,

    [ValidateSet('auto', 'none', 'codex', 'claude', 'both')]
    [string]$Client = 'auto',

    [string]$DataDirectory,

    [switch]$RegisterClients,

    [switch]$NoRegister,

    [switch]$NonInteractive,

    [switch]$Json,

    [ValidateSet('ja', 'en')]
    [string]$Language = 'ja',

    [Obsolete('Use -DataDirectory. An individual database path is no longer a setup target.')]
    [string]$Database,

    [Obsolete('pmgs setup installs the managed skill directly; a kit output path is unnecessary.')]
    [string]$KitOutput
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($RegisterClients -and $NoRegister) {
    throw '-RegisterClients and -NoRegister are mutually exclusive.'
}
if (-not [string]::IsNullOrWhiteSpace($Database)) {
    throw '-Database is no longer supported. Use -DataDirectory for the managed setup root.'
}
if (-not [string]::IsNullOrWhiteSpace($KitOutput)) {
    throw '-KitOutput is no longer supported. pmgs setup installs the managed skill directly.'
}
if (($Json -or $NonInteractive) -and -not ($RegisterClients -or $NoRegister)) {
    throw '-Json and -NonInteractive require -RegisterClients or -NoRegister.'
}

$repositoryRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$sourcePath = [System.IO.Path]::GetFullPath($SourceDirectory)
if (-not (Test-Path -LiteralPath $sourcePath -PathType Container)) {
    throw "PMGS source directory is not a directory: $sourcePath"
}
$uv = Get-Command uv -ErrorAction Stop

$setupArguments = @('run', '--frozen', 'pmgs', 'setup', $sourcePath, '--client', $Client, '--language', $Language)
if (-not [string]::IsNullOrWhiteSpace($ReleaseId)) {
    $setupArguments += @('--release', $ReleaseId)
}
if (-not [string]::IsNullOrWhiteSpace($DataDirectory)) {
    $setupArguments += @('--data-dir', [System.IO.Path]::GetFullPath($DataDirectory))
}
if ($RegisterClients) {
    $setupArguments += '--register'
}
elseif ($NoRegister) {
    $setupArguments += '--no-register'
}
if ($NonInteractive) {
    $setupArguments += '--non-interactive'
}
if ($Json) {
    $setupArguments += '--json'
}

if (-not $PSCmdlet.ShouldProcess($sourcePath, 'Run pmgs setup')) {
    return
}

Push-Location $repositoryRoot
try {
    & $uv.Source @setupArguments
    if ($LASTEXITCODE -ne 0) {
        throw "pmgs setup failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}

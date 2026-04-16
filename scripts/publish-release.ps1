[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ReleaseId,

    [string]$DestinationPath,

    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-RepoRoot {
    $scriptDir = Split-Path -Parent $PSCommandPath
    return (Resolve-Path (Join-Path $scriptDir '..')).Path
}

function Resolve-DestinationPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot,
        [string]$InputPath
    )

    if ([string]::IsNullOrWhiteSpace($InputPath)) {
        return (Join-Path $RepoRoot 'published/firewall-ingest')
    }

    if ([System.IO.Path]::IsPathRooted($InputPath)) {
        return $InputPath
    }

    return (Join-Path $RepoRoot $InputPath)
}

function Test-IsSubPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ParentPath,
        [Parameter(Mandatory = $true)]
        [string]$ChildPath
    )

    $resolvedParent = (Resolve-Path -LiteralPath $ParentPath).Path
    $resolvedChild = $ChildPath

    if (Test-Path -LiteralPath $ChildPath) {
        $resolvedChild = (Resolve-Path -LiteralPath $ChildPath).Path
    }
    else {
        $resolvedChild = [System.IO.Path]::GetFullPath($ChildPath)
    }

    $normalizedParent = $resolvedParent.TrimEnd([char[]]'\/') + [System.IO.Path]::DirectorySeparatorChar
    return ($resolvedChild.StartsWith($normalizedParent, [System.StringComparison]::OrdinalIgnoreCase) -or
        $resolvedChild.Equals($resolvedParent, [System.StringComparison]::OrdinalIgnoreCase))
}

try {
    $repoRoot = Get-RepoRoot
    $archiveReleasePath = Join-Path (Join-Path $repoRoot 'edl/releases/archive') $ReleaseId
    $manifestPath = Join-Path $archiveReleasePath 'manifest.json'

    if (-not (Test-Path -LiteralPath $archiveReleasePath)) {
        throw "Release '$ReleaseId' was not found under edl/releases/archive."
    }

    if (-not (Test-Path -LiteralPath $manifestPath)) {
        throw "Release '$ReleaseId' is missing manifest.json and will not be published."
    }

    $workingRoot = Join-Path $repoRoot 'edl/working'
    $approvedRoot = Join-Path $repoRoot 'edl/approved'
    $resolvedDestination = Resolve-DestinationPath -RepoRoot $repoRoot -InputPath $DestinationPath

    if ((Test-IsSubPath -ParentPath $workingRoot -ChildPath $resolvedDestination) -or
        (Test-IsSubPath -ParentPath $approvedRoot -ChildPath $resolvedDestination)) {
        throw "Destination path '$resolvedDestination' is not allowed. Do not publish into working or approved folders."
    }

    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json

    if ($DryRun) {
        Write-Host 'Dry run only. No files were copied.'
        Write-Host "Release ID   : $ReleaseId"
        Write-Host "Source       : $archiveReleasePath"
        Write-Host "Destination  : $resolvedDestination"
        Write-Host 'Files to publish:'

        foreach ($entry in $manifest.files) {
            Write-Host "- $($entry.path) (sha256: $($entry.sha256))"
        }
        Write-Host '- manifest.json'
        exit 0
    }

    if (-not (Test-Path -LiteralPath $resolvedDestination)) {
        New-Item -ItemType Directory -Path $resolvedDestination -Force | Out-Null
    }

    Get-ChildItem -Path $resolvedDestination -Force | Remove-Item -Recurse -Force

    $publishedFiles = New-Object System.Collections.Generic.List[string]

    foreach ($entry in $manifest.files) {
        $relativePath = $entry.path.Replace('/', '\\')
        $sourceFile = Join-Path $archiveReleasePath $relativePath
        $destinationFile = Join-Path $resolvedDestination $relativePath

        if (-not (Test-Path -LiteralPath $sourceFile)) {
            throw "Expected release file is missing: $sourceFile"
        }

        $destinationDir = Split-Path -Parent $destinationFile
        if (-not (Test-Path -LiteralPath $destinationDir)) {
            New-Item -ItemType Directory -Path $destinationDir -Force | Out-Null
        }

        Copy-Item -LiteralPath $sourceFile -Destination $destinationFile -Force
        $publishedFiles.Add("$($entry.path) (sha256: $($entry.sha256))") | Out-Null
    }

    Copy-Item -LiteralPath $manifestPath -Destination (Join-Path $resolvedDestination 'manifest.json') -Force

    Write-Host 'Publish succeeded.'
    Write-Host "Release ID  : $ReleaseId"
    Write-Host "Source      : $archiveReleasePath"
    Write-Host "Destination : $resolvedDestination"
    Write-Host 'Published files:'
    foreach ($file in $publishedFiles) {
        Write-Host "- $file"
    }
    Write-Host '- manifest.json'

    exit 0
}
catch {
    Write-Error "Publish failed: $($_.Exception.Message)"
    exit 1
}

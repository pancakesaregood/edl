[CmdletBinding()]
param(
    [string]$ReleaseId
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-RepoRoot {
    $scriptDir = Split-Path -Parent $PSCommandPath
    return (Resolve-Path (Join-Path $scriptDir '..')).Path
}

function Get-RelativePathNormalized {
    param(
        [Parameter(Mandatory = $true)]
        [string]$BasePath,
        [Parameter(Mandatory = $true)]
        [string]$TargetPath
    )

    $baseFullPath = [System.IO.Path]::GetFullPath($BasePath)
    $targetFullPath = [System.IO.Path]::GetFullPath($TargetPath)

    if (-not $baseFullPath.EndsWith('\') -and -not $baseFullPath.EndsWith('/')) {
        $baseFullPath += '\'
    }

    $baseUri = New-Object System.Uri($baseFullPath)
    $targetUri = New-Object System.Uri($targetFullPath)
    $relativeUri = $baseUri.MakeRelativeUri($targetUri)
    $relative = [System.Uri]::UnescapeDataString($relativeUri.ToString())

    return $relative.Replace('\', '/')
}

function Clear-DirectoryContents {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Cannot clear missing directory: $Path"
    }

    Get-ChildItem -Path $Path -Force | Remove-Item -Recurse -Force
}

try {
    $repoRoot = Get-RepoRoot
    $approvedRoot = Join-Path $repoRoot 'edl/approved'
    $releasesRoot = Join-Path $repoRoot 'edl/releases'
    $archiveRoot = Join-Path $releasesRoot 'archive'
    $currentRoot = Join-Path $releasesRoot 'current'

    foreach ($requiredDir in @($approvedRoot, $archiveRoot, $currentRoot)) {
        if (-not (Test-Path -LiteralPath $requiredDir)) {
            throw "Missing required directory: $requiredDir"
        }
    }

    if ([string]::IsNullOrWhiteSpace($ReleaseId)) {
        $ReleaseId = 'release-' + (Get-Date).ToUniversalTime().ToString('yyyyMMdd-HHmmss')
    }

    $releaseArchivePath = Join-Path $archiveRoot $ReleaseId
    if (Test-Path -LiteralPath $releaseArchivePath) {
        throw "Release '$ReleaseId' already exists at '$releaseArchivePath'."
    }

    $approvedFiles = Get-ChildItem -Path $approvedRoot -Filter '*.txt' -File -Recurse
    if ($approvedFiles.Count -eq 0) {
        throw "No approved EDL files found in '$approvedRoot'."
    }

    New-Item -ItemType Directory -Path $releaseArchivePath -Force | Out-Null

    foreach ($sourceFile in $approvedFiles) {
        $relativePath = (Get-RelativePathNormalized -BasePath $approvedRoot -TargetPath $sourceFile.FullName).Replace('/', '\')
        $destinationPath = Join-Path $releaseArchivePath $relativePath
        $destinationDir = Split-Path -Parent $destinationPath

        if (-not (Test-Path -LiteralPath $destinationDir)) {
            New-Item -ItemType Directory -Path $destinationDir -Force | Out-Null
        }

        Copy-Item -LiteralPath $sourceFile.FullName -Destination $destinationPath -Force
    }

    $sourceCommit = $null
    try {
        $sourceCommit = (git -C $repoRoot rev-parse HEAD 2>$null).Trim()
        if ([string]::IsNullOrWhiteSpace($sourceCommit)) {
            $sourceCommit = $null
        }
    }
    catch {
        $sourceCommit = $null
    }

    $manifestFiles = @()
    $releasedFiles = Get-ChildItem -Path $releaseArchivePath -Filter '*.txt' -File -Recurse | Sort-Object FullName

    foreach ($releasedFile in $releasedFiles) {
        $manifestFiles += [ordered]@{
            path      = Get-RelativePathNormalized -BasePath $releaseArchivePath -TargetPath $releasedFile.FullName
            sha256    = (Get-FileHash -Algorithm SHA256 -LiteralPath $releasedFile.FullName).Hash
            size_bytes = $releasedFile.Length
        }
    }

    $manifest = [ordered]@{
        release_id    = $ReleaseId
        created_at    = [DateTime]::UtcNow.ToString('o')
        created_by    = $env:USERNAME
        source_commit = $sourceCommit
        files         = $manifestFiles
    }

    $manifestPath = Join-Path $releaseArchivePath 'manifest.json'
    $manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $manifestPath -Encoding UTF8

    Clear-DirectoryContents -Path $currentRoot
    Copy-Item -Path (Join-Path $releaseArchivePath '*') -Destination $currentRoot -Recurse -Force

    Write-Host 'Release build succeeded.'
    Write-Host "Release ID    : $ReleaseId"
    Write-Host "Archive Path  : $releaseArchivePath"
    Write-Host "Current Path  : $currentRoot"
    Write-Host "File Count    : $($manifestFiles.Count)"
    Write-Host "Manifest Path : $manifestPath"

    exit 0
}
catch {
    Write-Error "Release build failed: $($_.Exception.Message)"
    exit 1
}

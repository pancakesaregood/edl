[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$FileName,

    [Parameter(Mandatory = $true)]
    [string]$Ticket
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

function Resolve-WorkingFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [string]$WorkingRoot
    )

    $candidatePaths = @()

    if (Test-Path -LiteralPath $Name) {
        $candidatePaths += (Resolve-Path -LiteralPath $Name).Path
    }

    $candidatePaths += (Join-Path $WorkingRoot $Name)

    foreach ($candidate in $candidatePaths) {
        if (-not (Test-Path -LiteralPath $candidate)) {
            continue
        }

        $resolved = (Resolve-Path -LiteralPath $candidate).Path
        $resolvedWorkingRoot = (Resolve-Path -LiteralPath $WorkingRoot).Path

        $workingRootWithSeparator = $resolvedWorkingRoot.TrimEnd([char[]]'\/') + [System.IO.Path]::DirectorySeparatorChar

        if ($resolved.StartsWith($workingRootWithSeparator, [System.StringComparison]::OrdinalIgnoreCase) -or
            $resolved.Equals($resolvedWorkingRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
            return $resolved
        }
    }

    throw "File '$Name' was not found under '$WorkingRoot'."
}

function Get-LockPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$WorkingRoot,
        [Parameter(Mandatory = $true)]
        [string]$WorkingFile,
        [Parameter(Mandatory = $true)]
        [string]$LocksRoot
    )

    $relative = Get-RelativePathNormalized -BasePath $WorkingRoot -TargetPath $WorkingFile
    $safeName = $relative -replace '[^A-Za-z0-9._-]', '_'
    return Join-Path $LocksRoot "$safeName.lock.json"
}

try {
    $repoRoot = Get-RepoRoot
    $workingRoot = Join-Path $repoRoot 'edl/working'
    $locksRoot = Join-Path $repoRoot 'locks'

    if (-not (Test-Path -LiteralPath $workingRoot)) {
        throw "Missing required folder: $workingRoot"
    }

    if (-not (Test-Path -LiteralPath $locksRoot)) {
        throw "Missing required folder: $locksRoot"
    }

    $workingFilePath = Resolve-WorkingFile -Name $FileName -WorkingRoot $workingRoot
    $relativeFileName = Get-RelativePathNormalized -BasePath $workingRoot -TargetPath $workingFilePath
    $lockPath = Get-LockPath -WorkingRoot $workingRoot -WorkingFile $workingFilePath -LocksRoot $locksRoot

    if (Test-Path -LiteralPath $lockPath) {
        $existingLock = Get-Content -LiteralPath $lockPath -Raw | ConvertFrom-Json
        throw "'$relativeFileName' is already locked by '$($existingLock.locked_by)' on '$($existingLock.machine)' for ticket '$($existingLock.ticket)' at '$($existingLock.timestamp)'."
    }

    $lock = [ordered]@{
        file_name = $relativeFileName
        locked_by = $env:USERNAME
        machine   = $env:COMPUTERNAME
        ticket    = $Ticket
        timestamp = [DateTime]::UtcNow.ToString('o')
    }

    $lock | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $lockPath -Encoding UTF8

    Write-Host "Checkout succeeded."
    Write-Host "File   : $relativeFileName"
    Write-Host "Ticket : $Ticket"
    Write-Host "Lock   : $lockPath"
    exit 0
}
catch {
    Write-Error "Checkout failed: $($_.Exception.Message)"
    exit 1
}

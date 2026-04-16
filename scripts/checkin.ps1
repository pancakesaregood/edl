[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$FileName,

    [Parameter(Mandatory = $true)]
    [string]$Ticket,

    [ValidateSet('Auto', 'IpOrCidr', 'Domain', 'Url')]
    [string]$EntryType = 'Auto',

    [switch]$IgnoreComments
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
    $validateScript = Join-Path $repoRoot 'scripts/validate.ps1'

    foreach ($requiredPath in @($workingRoot, $locksRoot, $validateScript)) {
        if (-not (Test-Path -LiteralPath $requiredPath)) {
            throw "Missing required path: $requiredPath"
        }
    }

    $workingFilePath = Resolve-WorkingFile -Name $FileName -WorkingRoot $workingRoot
    $relativeFileName = Get-RelativePathNormalized -BasePath $workingRoot -TargetPath $workingFilePath
    $lockPath = Get-LockPath -WorkingRoot $workingRoot -WorkingFile $workingFilePath -LocksRoot $locksRoot

    if (-not (Test-Path -LiteralPath $lockPath)) {
        throw "No lock file exists for '$relativeFileName'. Run checkout first."
    }

    $lock = Get-Content -LiteralPath $lockPath -Raw | ConvertFrom-Json

    if ($lock.file_name -ne $relativeFileName) {
        throw "Lock file metadata does not match file name '$relativeFileName'."
    }

    if ($lock.ticket -ne $Ticket) {
        throw "Ticket mismatch. Lock ticket is '$($lock.ticket)' but '$Ticket' was provided."
    }

    if ($lock.locked_by -ne $env:USERNAME) {
        throw "Lock is owned by '$($lock.locked_by)'. Current user is '$($env:USERNAME)'."
    }

    if ($lock.machine -ne $env:COMPUTERNAME) {
        Write-Warning "Lock was created on '$($lock.machine)' but checkin is running on '$($env:COMPUTERNAME)'."
    }

    $hostExe = (Get-Process -Id $PID).Path
    $validationArgs = @(
        '-NoProfile',
        '-ExecutionPolicy',
        'Bypass',
        '-File',
        $validateScript,
        '-Path',
        $workingFilePath,
        '-EntryType',
        $EntryType
    )

    if ($IgnoreComments) {
        $validationArgs += '-IgnoreComments'
    }

    & $hostExe @validationArgs
    $validationExitCode = $LASTEXITCODE

    if ($validationExitCode -ne 0) {
        throw "Validation failed for '$relativeFileName'."
    }

    Remove-Item -LiteralPath $lockPath -Force

    Write-Host 'Checkin succeeded.'
    Write-Host "File   : $relativeFileName"
    Write-Host "Ticket : $Ticket"
    Write-Host "Lock removed: $lockPath"
    exit 0
}
catch {
    Write-Error "Checkin failed: $($_.Exception.Message)"
    exit 1
}

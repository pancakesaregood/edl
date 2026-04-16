[CmdletBinding(DefaultParameterSetName = 'Single')]
param(
    [Parameter(ParameterSetName = 'Single', Position = 0)]
    [string]$Path,

    [Parameter(ParameterSetName = 'All', Mandatory = $true)]
    [switch]$All,

    [ValidateSet('Auto', 'IpOrCidr', 'Domain', 'Url', 'UrlPattern')]
    [string]$EntryType = 'Auto',

    [string]$TypeConfigPath = 'edl/list-types.json',

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

    return $relative.Replace('\\', '/')
}

function Resolve-InputFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$InputPath,
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot
    )

    $candidates = @()

    if (Test-Path -LiteralPath $InputPath) {
        $candidates += (Resolve-Path -LiteralPath $InputPath).Path
    }

    $candidates += (Join-Path $RepoRoot $InputPath)
    $candidates += (Join-Path (Join-Path $RepoRoot 'edl/working') $InputPath)
    $candidates += (Join-Path (Join-Path $RepoRoot 'edl/approved') $InputPath)

    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    throw "Could not resolve file path '$InputPath'."
}

function Get-DefaultEdlFiles {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot
    )

    $files = @()
    foreach ($folder in @('edl/working', 'edl/approved')) {
        $fullPath = Join-Path $RepoRoot $folder
        if (Test-Path -LiteralPath $fullPath) {
            $files += Get-ChildItem -Path $fullPath -Filter '*.txt' -File -Recurse
        }
    }

    return $files
}

function Normalize-EntryTypeName {
    param(
        [Parameter(Mandatory = $true)]
        [string]$TypeName
    )

    switch ($TypeName.ToLowerInvariant()) {
        'auto'       { return 'Auto' }
        'iporcidr'   { return 'IpOrCidr' }
        'ip'         { return 'IpOrCidr' }
        'cidr'       { return 'IpOrCidr' }
        'domain'     { return 'Domain' }
        'fqdn'       { return 'Domain' }
        'url'        { return 'Url' }
        'urlpattern' { return 'UrlPattern' }
        default {
            throw "Unsupported entry type '$TypeName'. Expected Auto, IpOrCidr, Domain, Url, or UrlPattern."
        }
    }
}

function Resolve-TypeConfigPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot,
        [Parameter(Mandatory = $true)]
        [string]$InputPath
    )

    if ([string]::IsNullOrWhiteSpace($InputPath)) {
        return $null
    }

    if ([System.IO.Path]::IsPathRooted($InputPath)) {
        return $InputPath
    }

    return (Join-Path $RepoRoot $InputPath)
}

function Get-TypeConfiguration {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot,
        [Parameter(Mandatory = $true)]
        [string]$ConfigPathInput
    )

    $resolvedPath = Resolve-TypeConfigPath -RepoRoot $RepoRoot -InputPath $ConfigPathInput

    $config = @{
        is_loaded    = $false
        path         = $resolvedPath
        default_type = 'Auto'
        file_map     = @{}
    }

    if ([string]::IsNullOrWhiteSpace($resolvedPath) -or -not (Test-Path -LiteralPath $resolvedPath)) {
        return $config
    }

    $json = Get-Content -LiteralPath $resolvedPath -Raw | ConvertFrom-Json

    if ($null -ne $json.default_entry_type -and -not [string]::IsNullOrWhiteSpace([string]$json.default_entry_type)) {
        $config.default_type = Normalize-EntryTypeName -TypeName ([string]$json.default_entry_type)
    }

    if ($null -ne $json.files) {
        foreach ($property in $json.files.PSObject.Properties) {
            $fileName = [string]$property.Name
            $entryType = Normalize-EntryTypeName -TypeName ([string]$property.Value)
            $config.file_map[$fileName.ToLowerInvariant()] = $entryType
        }
    }

    $config.is_loaded = $true
    return $config
}

function Test-IpOrCidr {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Value
    )

    if ($Value.Contains('/')) {
        $parts = $Value.Split('/')
        if ($parts.Count -ne 2) {
            return $false
        }

        $ipAddress = $null
        if (-not [System.Net.IPAddress]::TryParse($parts[0], [ref]$ipAddress)) {
            return $false
        }

        $prefixLength = 0
        if (-not [int]::TryParse($parts[1], [ref]$prefixLength)) {
            return $false
        }

        if ($ipAddress.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork) {
            return ($prefixLength -ge 0 -and $prefixLength -le 32)
        }

        if ($ipAddress.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetworkV6) {
            return ($prefixLength -ge 0 -and $prefixLength -le 128)
        }

        return $false
    }

    $ipOnly = $null
    return [System.Net.IPAddress]::TryParse($Value, [ref]$ipOnly)
}

function Test-Domain {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Value
    )

    if ($Value.Length -gt 253) {
        return $false
    }

    return ($Value -match '^(?=.{1,253}$)(?!-)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])$')
}

function Test-Url {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Value
    )

    $uri = $null
    if (-not [System.Uri]::TryCreate($Value, [System.UriKind]::Absolute, [ref]$uri)) {
        return $false
    }

    if ($uri.Scheme -notin @('http', 'https')) {
        return $false
    }

    if ([string]::IsNullOrWhiteSpace($uri.Host)) {
        return $false
    }

    return $true
}

function Test-UrlPattern {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Value
    )

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $false
    }

    if ($Value -match '\s') {
        return $false
    }

    # URL pattern supports wildcard '*' and optional anchored path '/...'.
    if ($Value -notmatch '^(?:(?<scheme>https?)://)?(?<host>[A-Za-z0-9*.-]+)(?<path>/\S*)?$') {
        return $false
    }

    $hostPart = $Matches['host']
    if ([string]::IsNullOrWhiteSpace($hostPart)) {
        return $false
    }

    if ($hostPart.StartsWith('.') -or $hostPart.EndsWith('.')) {
        return $false
    }

    if ($hostPart.Contains('..')) {
        return $false
    }

    if ($hostPart -notmatch '[A-Za-z0-9]') {
        return $false
    }

    $labels = $hostPart.Split('.')
    foreach ($label in $labels) {
        if ([string]::IsNullOrWhiteSpace($label)) {
            return $false
        }

        if ($label -notmatch '^[A-Za-z0-9*-]+$') {
            return $false
        }
    }

    return $true
}

function Resolve-FileEntryType {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RequestedType,
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(Mandatory = $true)]
        [hashtable]$TypeConfiguration
    )

    $normalizedRequested = Normalize-EntryTypeName -TypeName $RequestedType
    if ($normalizedRequested -ne 'Auto') {
        return $normalizedRequested
    }

    $fileName = [System.IO.Path]::GetFileName($FilePath).ToLowerInvariant()
    if ($TypeConfiguration.file_map.ContainsKey($fileName)) {
        return $TypeConfiguration.file_map[$fileName]
    }

    if ($TypeConfiguration.default_type -ne 'Auto') {
        return $TypeConfiguration.default_type
    }

    # Fallback heuristics if file is not in the type map.
    $name = [System.IO.Path]::GetFileNameWithoutExtension($FilePath)

    if ($name -match '(^|[-_])(ip|cidr)($|[-_])') {
        return 'IpOrCidr'
    }

    if ($name -match '(^|[-_])(domain|fqdn)($|[-_])') {
        return 'Domain'
    }

    if ($name -match '(^|[-_])(url|uri)($|[-_])') {
        return 'UrlPattern'
    }

    return 'Auto'
}

function Test-Entry {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Value,
        [Parameter(Mandatory = $true)]
        [string]$EntryType
    )

    switch ($EntryType) {
        'IpOrCidr'  { return (Test-IpOrCidr -Value $Value) }
        'Domain'    { return (Test-Domain -Value $Value) }
        'Url'       { return (Test-Url -Value $Value) }
        'UrlPattern'{ return (Test-UrlPattern -Value $Value) }
        default {
            return (
                (Test-IpOrCidr -Value $Value) -or
                (Test-Domain -Value $Value) -or
                (Test-UrlPattern -Value $Value) -or
                (Test-Url -Value $Value)
            )
        }
    }
}

function Normalize-Entry {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Value
    )

    return $Value.Trim().ToLowerInvariant()
}

function Validate-File {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot,
        [Parameter(Mandatory = $true)]
        [string]$RequestedEntryType,
        [Parameter(Mandatory = $true)]
        [hashtable]$TypeConfiguration,
        [switch]$IgnoreCommentsEnabled
    )

    $effectiveEntryType = Resolve-FileEntryType -RequestedType $RequestedEntryType -FilePath $FilePath -TypeConfiguration $TypeConfiguration
    $lines = Get-Content -LiteralPath $FilePath
    $seenEntries = @{}
    $duplicateLines = New-Object System.Collections.Generic.List[string]
    $invalidLines = New-Object System.Collections.Generic.List[string]

    $blankCount = 0
    $commentCount = 0
    $validCount = 0

    for ($i = 0; $i -lt $lines.Count; $i++) {
        $rawLine = [string]$lines[$i]
        $entry = $rawLine.Trim()
        $lineNumber = $i + 1

        if ([string]::IsNullOrWhiteSpace($entry)) {
            $blankCount++
            continue
        }

        if ($IgnoreCommentsEnabled -and $entry.StartsWith('#')) {
            $commentCount++
            continue
        }

        if (-not (Test-Entry -Value $entry -EntryType $effectiveEntryType)) {
            $invalidLines.Add("line ${lineNumber}: $entry") | Out-Null
            continue
        }

        $normalized = Normalize-Entry -Value $entry
        if ($seenEntries.ContainsKey($normalized)) {
            $duplicateLines.Add("line ${lineNumber}: $entry") | Out-Null
            continue
        }

        $seenEntries[$normalized] = $true
        $validCount++
    }

    return [ordered]@{
        file_path         = $FilePath
        relative_path     = Get-RelativePathNormalized -BasePath $RepoRoot -TargetPath $FilePath
        entry_type        = $effectiveEntryType
        total_lines       = $lines.Count
        valid_entries     = $validCount
        blank_lines       = $blankCount
        comment_lines     = $commentCount
        duplicate_count   = $duplicateLines.Count
        invalid_count     = $invalidLines.Count
        duplicate_entries = $duplicateLines
        invalid_entries   = $invalidLines
    }
}

$exitCode = 0

try {
    $repoRoot = Get-RepoRoot
    $typeConfiguration = Get-TypeConfiguration -RepoRoot $repoRoot -ConfigPathInput $TypeConfigPath
    $targets = @()

    if ($All -or [string]::IsNullOrWhiteSpace($Path)) {
        $targets = Get-DefaultEdlFiles -RepoRoot $repoRoot
        if ($targets.Count -eq 0) {
            throw 'No EDL .txt files were found under edl/working or edl/approved.'
        }

        $targets = $targets | ForEach-Object { $_.FullName }
    }
    else {
        $targets = @((Resolve-InputFile -InputPath $Path -RepoRoot $repoRoot))
    }

    $results = @()
    foreach ($target in $targets) {
        $results += Validate-File -FilePath $target -RepoRoot $repoRoot -RequestedEntryType $EntryType -TypeConfiguration $typeConfiguration -IgnoreCommentsEnabled:$IgnoreComments
    }

    if ($typeConfiguration.is_loaded) {
        Write-Host "Type map loaded from $($typeConfiguration.path)"
        Write-Host ''
    }

    foreach ($result in $results) {
        Write-Host "Validating $($result.relative_path) (type: $($result.entry_type))"
        Write-Host "  Total lines    : $($result.total_lines)"
        Write-Host "  Valid entries  : $($result.valid_entries)"
        Write-Host "  Blank lines    : $($result.blank_lines)"
        Write-Host "  Comment lines  : $($result.comment_lines)"
        Write-Host "  Duplicates     : $($result.duplicate_count)"
        Write-Host "  Invalid        : $($result.invalid_count)"

        if ($result.duplicate_count -gt 0) {
            Write-Host '  Duplicate entries:'
            foreach ($dup in $result.duplicate_entries) {
                Write-Host "    - $dup"
            }
            $exitCode = 1
        }

        if ($result.invalid_count -gt 0) {
            Write-Host '  Invalid entries:'
            foreach ($bad in $result.invalid_entries) {
                Write-Host "    - $bad"
            }
            $exitCode = 1
        }

        Write-Host ''
    }

    if ($exitCode -eq 0) {
        Write-Host "Validation succeeded for $($results.Count) file(s)."
    }
    else {
        Write-Error 'Validation failed for one or more files.'
    }
}
catch {
    Write-Error "Validation failed: $($_.Exception.Message)"
    $exitCode = 1
}

exit $exitCode

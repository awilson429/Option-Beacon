Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-JsonUtf8 {
    param(
        [Parameter(Mandatory = $true)] [object] $Value,
        [Parameter(Mandatory = $true)] [string] $Path,
        [int] $Depth = 12
    )
    $json = $Value | ConvertTo-Json -Depth $Depth
    [System.IO.File]::WriteAllText($Path, $json, (New-Object System.Text.UTF8Encoding($false)))
}

function Read-BackupConfiguration {
    param([Parameter(Mandatory = $true)] [string] $Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Backup configuration not found: $Path"
    }
    $raw = Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json
    $maximum = if ($null -ne $raw.MaximumArtifactSizeMB) {
        [int] $raw.MaximumArtifactSizeMB
    } else {
        2048
    }
    if ($maximum -lt 1) {
        throw "MaximumArtifactSizeMB must be at least 1."
    }
    $additional = @()
    if ($null -ne $raw.AdditionalExportPaths) {
        $additional = @($raw.AdditionalExportPaths | ForEach-Object { [string] $_ })
    }
    [pscustomobject] @{
        PreferredVolumeLabel   = [string] $raw.PreferredVolumeLabel
        FallbackDriveRoot      = [string] $raw.FallbackDriveRoot
        DestinationFolder      = [string] $raw.DestinationFolder
        DatabaseDumpRequired   = [bool] $raw.DatabaseDumpRequired
        PgDumpPath             = [string] $raw.PgDumpPath
        ProtectedSecretsSource = [string] $raw.ProtectedSecretsSource
        AdditionalExportPaths  = $additional
        MaximumArtifactSizeMB  = $maximum
    }
}

function Resolve-BackupDestination {
    param(
        [Parameter(Mandatory = $true)] [object] $Configuration,
        [string] $DestinationRootOverride = "",
        [switch] $AllowNonSsdDestination
    )

    if ($DestinationRootOverride) {
        if (-not $AllowNonSsdDestination) {
            throw "DestinationRootOverride is test-only and requires -AllowNonSsdDestination."
        }
        $override = [System.IO.Path]::GetFullPath($DestinationRootOverride)
        return [pscustomobject] @{
            DriveRoot = [System.IO.Path]::GetPathRoot($override)
            BackupRoot = $override.TrimEnd('\')
            Detection = "explicit-test-override"
            VolumeLabel = "TEST_OVERRIDE"
        }
    }

    $expectedLabel = ([string] $Configuration.PreferredVolumeLabel).Trim()
    if (-not $expectedLabel) {
        throw "PreferredVolumeLabel must be configured."
    }
    $matches = @(
        [System.IO.DriveInfo]::GetDrives() | Where-Object {
            $_.IsReady -and $_.VolumeLabel -ieq $expectedLabel
        }
    )
    if ($matches.Count -gt 1) {
        throw "More than one ready drive has volume label '$expectedLabel'. Disconnect the unintended drive and retry."
    }

    $drive = $null
    $detection = "volume-label"
    if ($matches.Count -eq 1) {
        $drive = $matches[0]
    } else {
        $fallback = ([string] $Configuration.FallbackDriveRoot).Trim()
        if (-not $fallback) {
            throw "Samsung T5 not found by label '$expectedLabel' and no fallback drive is configured."
        }
        try {
            $candidate = New-Object System.IO.DriveInfo($fallback)
        } catch {
            throw "Fallback drive '$fallback' is invalid. Label the SSD '$expectedLabel' or correct backup.config.json."
        }
        if (-not $candidate.IsReady -or $candidate.VolumeLabel -ine $expectedLabel) {
            $actual = if ($candidate.IsReady) { $candidate.VolumeLabel } else { "not ready" }
            throw "Expected SSD '$expectedLabel' was not found. Fallback $fallback is '$actual'; refusing to use an unintended drive."
        }
        $drive = $candidate
        $detection = "verified-fallback"
    }

    $folder = ([string] $Configuration.DestinationFolder).Trim().Trim('\', '/')
    if (-not $folder -or $folder -match '[\\/:*?""<>|]') {
        throw "DestinationFolder must be a safe folder name, not a path."
    }
    $driveRoot = [System.IO.Path]::GetFullPath($drive.RootDirectory.FullName)
    $backupRoot = [System.IO.Path]::GetFullPath((Join-Path $driveRoot $folder))
    if (-not $backupRoot.StartsWith($driveRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
        $backupRoot -eq $driveRoot) {
        throw "Resolved destination is outside the detected SSD."
    }
    [pscustomobject] @{
        DriveRoot = $driveRoot
        BackupRoot = $backupRoot.TrimEnd('\')
        Detection = $detection
        VolumeLabel = $drive.VolumeLabel
    }
}

function Test-BackupRelativePath {
    param(
        [Parameter(Mandatory = $true)] [string] $RelativePath,
        [long] $Length = 0,
        [int] $MaximumArtifactSizeMB = 2048
    )

    $path = $RelativePath.Replace('\', '/').TrimStart('/')
    $parts = @($path.Split('/'))
    $excludedDirectories = @(
        ".git", ".venv", "venv", "env", "node_modules", ".next", "__pycache__",
        ".pytest_cache", ".codex-test-deps", ".analysis-cache"
    )
    foreach ($part in $parts) {
        if ($excludedDirectories -contains $part -or $part -like ".test-temp-*" -or $part -like ".tmp-*") {
            return [pscustomobject] @{ Include = $false; Reason = "generated-or-cache-directory" }
        }
    }
    $name = [System.IO.Path]::GetFileName($path)
    if ($name -ieq "secrets.toml" -or $name -ieq "backup.config.json" -or
        $name -like ".env*" -or $name -match '(?i)\.(pem|key|p12|pfx|kdbx)$') {
        return [pscustomobject] @{ Include = $false; Reason = "secret-or-private-configuration" }
    }
    if ($Length -gt ([long] $MaximumArtifactSizeMB * 1MB)) {
        return [pscustomobject] @{ Include = $false; Reason = "exceeds-maximum-artifact-size" }
    }
    $allowed = @(
        ".json", ".jsonl", ".csv", ".db", ".sqlite", ".sqlite3", ".html",
        ".png", ".jpg", ".jpeg", ".md", ".txt", ".log"
    )
    $extension = [System.IO.Path]::GetExtension($name).ToLowerInvariant()
    if ($allowed -notcontains $extension) {
        return [pscustomobject] @{ Include = $false; Reason = "unsupported-untracked-artifact-type" }
    }
    [pscustomobject] @{ Include = $true; Reason = "recovery-or-research-artifact" }
}

function Protect-BackupText {
    param([AllowNull()] [string] $Text)
    if ($null -eq $Text) { return "" }
    $safe = $Text
    $safe = [regex]::Replace($safe, '(?i)postgres(?:ql)?://[^\s""'']+', '[REDACTED_DATABASE_URL]')
    $safe = [regex]::Replace($safe, '(?i)(https?://)[^/@\s:]+:[^/@\s]+@', '$1[REDACTED]@')
    $safe = [regex]::Replace($safe, '(?i)((?:TOKEN|KEY|PASSWORD|SECRET)\s*[=:]\s*)[^\s,;]+', '$1[REDACTED]')
    return $safe
}

function ConvertFrom-GitStatusPorcelain {
    param([AllowNull()] [string] $StatusText)
    $modified = New-Object System.Collections.Generic.List[string]
    $untracked = New-Object System.Collections.Generic.List[string]
    if ($StatusText) {
        foreach ($line in ($StatusText -split "`r?`n")) {
            if ($line.Length -lt 4) { continue }
            $code = $line.Substring(0, 2)
            $path = $line.Substring(3).Trim()
            if ($code -eq "??") {
                $untracked.Add($path)
            } elseif ($code -ne "!!") {
                $modified.Add($path)
            }
        }
    }
    [pscustomobject] @{
        ModifiedTracked = @($modified)
        Untracked = @($untracked)
    }
}

function Get-BackupFinalState {
    param(
        [bool] $CoreVerified,
        [bool] $DatabaseRequired,
        [bool] $DatabaseSucceeded,
        [int] $WarningCount = 0,
        [int] $FatalErrorCount = 0
    )
    if (-not $CoreVerified -or $FatalErrorCount -gt 0) { return "BACKUP FAILED" }
    if ($DatabaseRequired -and -not $DatabaseSucceeded) { return "BACKUP PARTIAL" }
    if ($WarningCount -gt 0) { return "BACKUP SUCCESSFUL WITH WARNINGS" }
    return "BACKUP SUCCESSFUL"
}

function Get-OptionBeaconSecretInventory {
    param([Parameter(Mandatory = $true)] [string] $RepositoryPath)

    $inventory = [ordered] @{}
    function Add-InventoryItem {
        param([string] $Name, [string] $Requirement, [string] $Sensitivity, [string] $Purpose)
        if (-not $inventory.Contains($Name)) {
            $inventory[$Name] = [pscustomobject] @{
                name = $Name
                requirement = $Requirement
                sensitivity = $Sensitivity
                purpose = $Purpose
                locally_detected = $false
            }
        }
    }
    Add-InventoryItem "DATABASE_URL" "required-production" "secret" "PostgreSQL/Neon connection"
    Add-InventoryItem "TRADIER_ACCESS_TOKEN" "required-provider" "secret" "Tradier market/option data"
    Add-InventoryItem "FINNHUB_API_KEY" "optional-provider" "secret" "Finnhub movers/news context"
    Add-InventoryItem "TRADIER_API_BASE_URL" "optional" "non-secret" "Tradier endpoint override"
    Add-InventoryItem "NEXT_PUBLIC_OPTIONBEACON_API_URL" "development-and-deployment" "non-secret" "Next.js FastAPI base URL"
    Add-InventoryItem "OPTIONBEACON_CORS_ORIGINS" "deployment" "non-secret" "FastAPI allowed origins"

    $optionNames = @(
        "OPTION_BEACON_ATTENTION_COUNT", "OPTION_BEACON_DATA_BASE_URL", "OPTION_BEACON_SYMBOLS",
        "OPTION_BEACON_TOP_MOVER_COUNT", "OPTIONBEACON_ALLOWED_TRADE_SYMBOLS",
        "OPTIONBEACON_DB_CONNECT_TIMEOUT_SECONDS", "OPTIONBEACON_EARLIEST_ENTRY_TIME",
        "OPTIONBEACON_ENTRY_FILL_TOWARD_ASK", "OPTIONBEACON_ENVIRONMENT", "OPTIONBEACON_EOD_EXIT_TIME_ET",
        "OPTIONBEACON_EXECUTION_MODE", "OPTIONBEACON_FILTERED_ENABLED", "OPTIONBEACON_FORCE_CLOSE_END_OF_DAY",
        "OPTIONBEACON_LATEST_ENTRY_TIME", "OPTIONBEACON_LOSS_COOLDOWN_MINUTES",
        "OPTIONBEACON_MAX_CONSECUTIVE_LOSSES", "OPTIONBEACON_MAX_DAILY_LOSS_DOLLARS",
        "OPTIONBEACON_MAX_DOLLARS_PER_TRADE", "OPTIONBEACON_MAX_HOLD_MINUTES",
        "OPTIONBEACON_MAX_OPEN_POSITIONS", "OPTIONBEACON_MAX_OPTION_SPREAD_PERCENT",
        "OPTIONBEACON_MAX_TOTAL_DEPLOYED_CAPITAL", "OPTIONBEACON_MAX_TRADES_PER_DAY",
        "OPTIONBEACON_MIN_BEACON_SCORE", "OPTIONBEACON_MIN_OPTION_OPEN_INTEREST",
        "OPTIONBEACON_MIN_OPTION_VOLUME", "OPTIONBEACON_MIRROR_ENABLED",
        "OPTIONBEACON_MIRROR_V2_SHADOW_ENABLED", "OPTIONBEACON_OPPORTUNITY_RANKING_V2",
        "OPTIONBEACON_PAPER_ACCOUNT_SIZE", "OPTIONBEACON_PROFIT_TARGET_PERCENT",
        "OPTIONBEACON_QUERY_EGRESS_DIAGNOSTICS", "OPTIONBEACON_REQUIRE_DURABLE_STORAGE",
        "OPTIONBEACON_SCAN_SECONDS", "OPTIONBEACON_SCANNER_ID", "OPTIONBEACON_STOP_LOSS_PERCENT",
        "OPTIONBEACON_TRADING_ENABLED", "OPTIONBEACON_TRAILING_PROFIT_ENABLED",
        "OPTIONBEACON_VERBOSE_STORAGE_DIAGNOSTICS", "MIRROR_EXPERIMENT_START_DATE",
        "MIRROR_V2_EXPERIMENT_START_DATE"
    )
    foreach ($name in $optionNames) {
        Add-InventoryItem $name "optional" "non-secret" "Application/worker behavior configuration"
    }
    $capitalSuffixes = @(
        "STARTING_CAPITAL", "RISK_PER_TRADE_PCT", "MAX_TOTAL_OPEN_RISK_PCT",
        "MAX_CONCURRENT_POSITIONS", "MAX_DAILY_LOSS_PCT", "DRAWDOWN_WARNING_PCT",
        "DRAWDOWN_REDUCED_PCT", "DRAWDOWN_HALT_PCT", "REDUCED_RISK_MULTIPLIER",
        "MAX_SPREAD_PCT", "MIN_OPEN_INTEREST", "MIN_VOLUME", "STALE_AFTER_SECONDS",
        "COMMISSION_PER_CONTRACT", "ENTRY_SLIPPAGE_FRACTION", "EXIT_SLIPPAGE_FRACTION"
    )
    foreach ($lane in @("OB", "BROAD")) {
        foreach ($suffix in $capitalSuffixes) {
            Add-InventoryItem "${lane}_${suffix}" "optional" "non-secret" "Simulated capital-readiness configuration"
        }
    }

    $candidateFiles = @(
        (Join-Path $RepositoryPath ".streamlit\secrets.toml"),
        (Join-Path $RepositoryPath ".env"),
        (Join-Path $RepositoryPath "frontend\.env.local")
    )
    foreach ($candidate in $candidateFiles) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
        foreach ($line in (Get-Content -LiteralPath $candidate)) {
            if ($line -match '^\s*([A-Z][A-Z0-9_]+)\s*=') {
                $name = $Matches[1]
                if (-not $inventory.Contains($name)) {
                    Add-InventoryItem $name "locally-detected" "secret-unknown" "Local configuration"
                }
                $inventory[$name].locally_detected = $true
            }
        }
    }
    return @($inventory.Values | Sort-Object name)
}

function Update-LatestPointer {
    param(
        [Parameter(Mandatory = $true)] [string] $BackupRoot,
        [Parameter(Mandatory = $true)] [string] $SnapshotName,
        [Parameter(Mandatory = $true)] [string] $FinalState
    )
    if ($FinalState -notin @("BACKUP SUCCESSFUL", "BACKUP SUCCESSFUL WITH WARNINGS")) {
        return $false
    }
    $resolvedRoot = [System.IO.Path]::GetFullPath($BackupRoot).TrimEnd('\')
    $latest = [System.IO.Path]::GetFullPath((Join-Path $resolvedRoot "LATEST"))
    if (-not $latest.StartsWith($resolvedRoot + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "LATEST pointer resolved outside the backup root."
    }
    if (-not (Test-Path -LiteralPath $latest)) {
        New-Item -ItemType Directory -Path $latest | Out-Null
    }
    $pointer = Join-Path $latest "CURRENT_SNAPSHOT.txt"
    $temporary = "$pointer.new-$([guid]::NewGuid().ToString('N'))"
    [System.IO.File]::WriteAllText($temporary, "$SnapshotName`r`n", (New-Object System.Text.UTF8Encoding($false)))
    if (Test-Path -LiteralPath $pointer) {
        $previous = Join-Path $latest "PREVIOUS_SNAPSHOT.txt"
        Copy-Item -LiteralPath $pointer -Destination $previous -Force
        Move-Item -LiteralPath $temporary -Destination $pointer -Force
    } else {
        Move-Item -LiteralPath $temporary -Destination $pointer
    }
    return $true
}

Export-ModuleMember -Function @(
    "Write-JsonUtf8",
    "Read-BackupConfiguration",
    "Resolve-BackupDestination",
    "Test-BackupRelativePath",
    "Protect-BackupText",
    "ConvertFrom-GitStatusPorcelain",
    "Get-BackupFinalState",
    "Get-OptionBeaconSecretInventory",
    "Update-LatestPointer"
)

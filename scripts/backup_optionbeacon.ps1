[CmdletBinding()]
param(
    [Alias("dry-run")]
    [switch] $DryRun,
    [string] $ConfigPath = "",
    [string] $RepositoryPath = "",
    [string] $DestinationRootOverride = "",
    [switch] $AllowNonSsdDestination
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$defaultRepository = [System.IO.Path]::GetFullPath((Join-Path $scriptDirectory ".."))
$repository = if ($RepositoryPath) {
    [System.IO.Path]::GetFullPath($RepositoryPath)
} else {
    $defaultRepository
}
$modulePath = Join-Path $scriptDirectory "OptionBeaconBackup.psm1"
Import-Module $modulePath -Force

$script:LogPath = $null
$script:Warnings = New-Object System.Collections.Generic.List[string]
$script:Errors = New-Object System.Collections.Generic.List[string]

function Write-BackupMessage {
    param([string] $Message, [ConsoleColor] $Color = [ConsoleColor]::Gray)
    $safe = Protect-BackupText $Message
    Write-Host $safe -ForegroundColor $Color
    if ($script:LogPath) {
        Add-Content -LiteralPath $script:LogPath -Value "$(Get-Date -Format o) $safe" -Encoding UTF8
    }
}

function Add-BackupWarning {
    param([string] $Message)
    $safe = Protect-BackupText $Message
    $script:Warnings.Add($safe)
    Write-BackupMessage "WARNING: $safe" Yellow
}

function Add-BackupError {
    param([string] $Message)
    $safe = Protect-BackupText $Message
    $script:Errors.Add($safe)
    Write-BackupMessage "ERROR: $safe" Red
}

function Invoke-GitText {
    param([string[]] $Arguments, [switch] $AllowFailure)
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = @(& git -C $repository @Arguments 2>&1)
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    $text = ($output | ForEach-Object { [string] $_ }) -join "`r`n"
    if ($code -ne 0 -and -not $AllowFailure) {
        throw "Git command failed: git $($Arguments -join ' ') - $(Protect-BackupText $text)"
    }
    [pscustomobject] @{ ExitCode = $code; Text = $text; Lines = @($output) }
}

function Copy-FilePreservingPath {
    param([string] $Source, [string] $DestinationRoot, [string] $RelativePath)
    $destination = Join-Path $DestinationRoot $RelativePath
    $parent = Split-Path -Parent $destination
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    Copy-Item -LiteralPath $Source -Destination $destination -Force
    return $destination
}

function Get-DatabaseUrlSafely {
    $configured = [Environment]::GetEnvironmentVariable("DATABASE_URL", "Process")
    if ($configured) { return $configured.Trim() }
    foreach ($candidate in @(
        (Join-Path $repository ".streamlit\secrets.toml"),
        (Join-Path $repository ".env")
    )) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
        foreach ($line in (Get-Content -LiteralPath $candidate)) {
            if ($line -match '^\s*DATABASE_URL\s*=\s*[""''](.+)[""'']\s*$') {
                return $Matches[1]
            }
            if ($line -match '^\s*DATABASE_URL\s*=\s*([^#\s]+)') {
                return $Matches[1]
            }
        }
    }
    return ""
}

function Get-ConfiguredExecutable {
    param([string] $ConfiguredPath, [string] $CommandName)
    if ($ConfiguredPath) {
        $resolved = [System.IO.Path]::GetFullPath($ConfiguredPath)
        if (Test-Path -LiteralPath $resolved -PathType Leaf) { return $resolved }
        return $null
    }
    $command = Get-Command $CommandName -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    return $null
}

function Invoke-DatabaseProcess {
    param(
        [Parameter(Mandatory = $true)] [string] $Executable,
        [Parameter(Mandatory = $true)] [string] $Arguments,
        [string] $DatabaseUrl = ""
    )
    $info = New-Object System.Diagnostics.ProcessStartInfo
    $info.FileName = $Executable
    $info.Arguments = $Arguments
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    if ($DatabaseUrl) {
        $info.EnvironmentVariables["PGDATABASE"] = $DatabaseUrl
    }
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $info
    [void] $process.Start()
    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    $process.WaitForExit()
    [pscustomobject] @{
        ExitCode = $process.ExitCode
        StandardOutput = Protect-BackupText $stdout
        StandardError = Protect-BackupText $stderr
    }
}

function Get-CandidateArtifacts {
    param([object] $Configuration, [string[]] $GitUntracked, [string[]] $GitTracked)
    $candidates = New-Object 'System.Collections.Generic.Dictionary[string,System.IO.FileInfo]' ([System.StringComparer]::OrdinalIgnoreCase)
    $tracked = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($relative in $GitTracked) { [void] $tracked.Add($relative.Replace('\', '/')) }
    foreach ($relative in $GitUntracked) {
        $clean = $relative.Trim('""')
        $full = Join-Path $repository $clean
        if (Test-Path -LiteralPath $full -PathType Leaf) {
            $candidates[$clean] = Get-Item -LiteralPath $full
        }
    }
    foreach ($file in (Get-ChildItem -LiteralPath $repository -File -Force)) {
        if (-not $tracked.Contains($file.Name.Replace('\', '/'))) {
            $candidates[$file.Name] = $file
        }
    }
    foreach ($configuredPath in @($Configuration.AdditionalExportPaths)) {
        if (-not $configuredPath) { continue }
        $full = if ([System.IO.Path]::IsPathRooted($configuredPath)) {
            [System.IO.Path]::GetFullPath($configuredPath)
        } else {
            [System.IO.Path]::GetFullPath((Join-Path $repository $configuredPath))
        }
        if (-not $full.StartsWith($repository + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
            Add-BackupWarning "AdditionalExportPaths entry is outside the repository and was excluded: $configuredPath"
            continue
        }
        if (Test-Path -LiteralPath $full -PathType Leaf) {
            $relative = $full.Substring($repository.Length + 1)
            $candidates[$relative] = Get-Item -LiteralPath $full
        } elseif (Test-Path -LiteralPath $full -PathType Container) {
            foreach ($file in (Get-ChildItem -LiteralPath $full -Recurse -File -ErrorAction SilentlyContinue)) {
                $relative = $file.FullName.Substring($repository.Length + 1)
                $candidates[$relative] = $file
            }
        } else {
            Add-BackupWarning "Configured export path does not exist: $configuredPath"
        }
    }
    return $candidates
}

function Get-DirectoryStatistics {
    param([string] $Path)
    $files = @(Get-ChildItem -LiteralPath $Path -Recurse -File -ErrorAction SilentlyContinue)
    $bytes = ($files | Measure-Object -Property Length -Sum).Sum
    if ($null -eq $bytes) { $bytes = 0 }
    [pscustomobject] @{ file_count = $files.Count; bytes = [long] $bytes }
}

function Test-ArtifactContainsSecretMaterial {
    param([string] $Path)
    $extension = [System.IO.Path]::GetExtension($Path).ToLowerInvariant()
    if ($extension -notin @(".json", ".jsonl", ".csv", ".html", ".md", ".txt", ".log")) {
        return $false
    }
    $reader = New-Object System.IO.StreamReader($Path)
    try {
        while (-not $reader.EndOfStream) {
            $line = $reader.ReadLine()
            if ($line -match '(?i)postgres(?:ql)?://[^\s""'']+' -or
                $line -match '(?i)(?:TOKEN|API_KEY|PASSWORD|SECRET)[""'']?\s*[:=]\s*[""'']?[A-Za-z0-9_\-]{12,}') {
                return $true
            }
        }
    } finally {
        $reader.Dispose()
    }
    return $false
}

if (-not (Test-Path -LiteralPath $repository -PathType Container)) {
    Write-Host "BACKUP FAILED: Repository path does not exist: $repository" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path -LiteralPath (Join-Path $repository ".git") -PathType Container)) {
    Write-Host "BACKUP FAILED: Repository path is not an OptionBeacon Git working tree." -ForegroundColor Red
    exit 1
}

if (-not $ConfigPath) {
    $localConfig = Join-Path $repository "backup.config.json"
    $ConfigPath = if (Test-Path -LiteralPath $localConfig) {
        $localConfig
    } else {
        Join-Path $repository "backup.config.example.json"
    }
} elseif (-not [System.IO.Path]::IsPathRooted($ConfigPath)) {
    $ConfigPath = Join-Path $repository $ConfigPath
}

try {
    $configuration = Read-BackupConfiguration -Path $ConfigPath
    $destination = Resolve-BackupDestination -Configuration $configuration `
        -DestinationRootOverride $DestinationRootOverride `
        -AllowNonSsdDestination:$AllowNonSsdDestination
} catch {
    Write-Host "BACKUP FAILED: $(Protect-BackupText $_.Exception.Message)" -ForegroundColor Red
    Write-Host "Confirm the Samsung T5 is connected and labeled correctly, or update backup.config.json." -ForegroundColor Yellow
    exit 1
}

try {
    $inside = Invoke-GitText -Arguments @("rev-parse", "--is-inside-work-tree")
    if ($inside.Text.Trim() -ne "true") { throw "Not inside a Git working tree." }
    $head = (Invoke-GitText -Arguments @("rev-parse", "HEAD")).Text.Trim()
    $branch = (Invoke-GitText -Arguments @("branch", "--show-current")).Text.Trim()
    $statusText = (Invoke-GitText -Arguments @("status", "--porcelain=v1", "--untracked-files=all")).Text
    $status = ConvertFrom-GitStatusPorcelain $statusText
    $trackedFiles = @((Invoke-GitText -Arguments @("ls-files")).Lines | ForEach-Object { [string] $_ } | Where-Object { $_ })
    $untrackedFiles = @((Invoke-GitText -Arguments @("ls-files", "--others", "--exclude-standard")).Lines | ForEach-Object { [string] $_ } | Where-Object { $_ })
    $remoteText = Protect-BackupText (Invoke-GitText -Arguments @("remote", "-v")).Text
    $branchesText = (Invoke-GitText -Arguments @("branch", "--all", "--no-color")).Text
    $tagsText = (Invoke-GitText -Arguments @("tag", "--list")).Text
} catch {
    Write-Host "BACKUP FAILED: Git audit failed: $(Protect-BackupText $_.Exception.Message)" -ForegroundColor Red
    exit 1
}

$pgDump = Get-ConfiguredExecutable -ConfiguredPath $configuration.PgDumpPath -CommandName "pg_dump"
$databaseUrl = Get-DatabaseUrlSafely
$secretInventory = @(Get-OptionBeaconSecretInventory -RepositoryPath $repository)
$candidateArtifacts = Get-CandidateArtifacts -Configuration $configuration -GitUntracked $untrackedFiles -GitTracked $trackedFiles
$includedArtifacts = New-Object System.Collections.Generic.List[object]
$excludedArtifacts = New-Object System.Collections.Generic.List[object]
foreach ($entry in $candidateArtifacts.GetEnumerator()) {
    $decision = Test-BackupRelativePath -RelativePath $entry.Key -Length $entry.Value.Length `
        -MaximumArtifactSizeMB $configuration.MaximumArtifactSizeMB
    if ($decision.Include -and (Test-ArtifactContainsSecretMaterial -Path $entry.Value.FullName)) {
        $decision = [pscustomobject] @{ Include = $false; Reason = "potential-secret-material" }
    }
    $record = [pscustomobject] @{
        path = $entry.Key.Replace('\', '/')
        bytes = [long] $entry.Value.Length
        reason = $decision.Reason
    }
    if ($decision.Include) { $includedArtifacts.Add($record) } else { $excludedArtifacts.Add($record) }
}

Write-BackupMessage "Repository: $repository" Cyan
Write-BackupMessage "Destination: $($destination.BackupRoot)" Cyan
Write-BackupMessage "SSD detection: $($destination.Detection) ($($destination.VolumeLabel))" Cyan
Write-BackupMessage "Git: $branch at $head" Cyan
Write-BackupMessage "Working tree: $($status.ModifiedTracked.Count) modified tracked, $($status.Untracked.Count) untracked" Cyan
Write-BackupMessage "Artifacts: $($includedArtifacts.Count) included, $($excludedArtifacts.Count) excluded" Cyan
Write-BackupMessage "Database URL configured: $([bool] $databaseUrl); pg_dump available: $([bool] $pgDump)" Cyan
Write-BackupMessage "Secrets: names inventoried; plaintext secret files will not be copied" Cyan

if ($DryRun) {
    Write-BackupMessage "" Gray
    Write-BackupMessage "DRY RUN ONLY - no snapshot was created." Yellow
    Write-BackupMessage "Would create a Git bundle, tracked working-tree copy, selected local artifacts, database dump, manifests, and recovery docs." Gray
    if ($configuration.DatabaseDumpRequired -and (-not $databaseUrl -or -not $pgDump)) {
        Write-BackupMessage "A real backup would be PARTIAL because the required database dump cannot currently run." Yellow
    }
    exit 0
}

$backupRoot = $destination.BackupRoot
$snapshotsRoot = Join-Path $backupRoot "SNAPSHOTS"
$recoveryRoot = Join-Path $backupRoot "RECOVERY"
$globalLogsRoot = Join-Path $backupRoot "logs"
foreach ($directory in @($backupRoot, $snapshotsRoot, $recoveryRoot, $globalLogsRoot)) {
    if (-not (Test-Path -LiteralPath $directory)) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }
}

$baseName = Get-Date -Format "yyyy-MM-dd_HHmmss"
$snapshotName = $baseName
$counter = 1
while (Test-Path -LiteralPath (Join-Path $snapshotsRoot $snapshotName)) {
    $snapshotName = "{0}_{1:D2}" -f $baseName, $counter
    $counter += 1
}
$incompleteName = ".incomplete-$snapshotName-$([guid]::NewGuid().ToString('N'))"
$staging = Join-Path $snapshotsRoot $incompleteName
$finalSnapshot = Join-Path $snapshotsRoot $snapshotName
$paths = [ordered] @{}
foreach ($name in @("repository", "git", "database", "configuration", "exports", "manifests", "logs")) {
    $paths[$name] = Join-Path $staging $name
    New-Item -ItemType Directory -Path $paths[$name] -Force | Out-Null
}
$script:LogPath = Join-Path $paths.logs "backup.log"
Write-BackupMessage "Staging snapshot: $incompleteName" Cyan

$gitBundleSucceeded = $false
$repositoryCopySucceeded = $false
$databaseSucceeded = $false
$databaseStatus = "not-attempted"
$databaseVersion = $null
$databaseVerification = "not-attempted"
$configurationStatus = "templates-and-name-only-inventory"
$protectedSecretsStatus = "not-configured"
$copiedTracked = 0
$copiedArtifacts = 0

try {
    foreach ($relative in $trackedFiles) {
        $source = Join-Path $repository $relative
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
            Add-BackupWarning "Tracked path was missing from the working tree: $relative"
            continue
        }
        [void] (Copy-FilePreservingPath -Source $source -DestinationRoot $paths.repository -RelativePath $relative)
        $copiedTracked += 1
    }
    $repositoryCopySucceeded = $copiedTracked -gt 0

    foreach ($artifact in $includedArtifacts) {
        $source = Join-Path $repository $artifact.path
        if (Test-Path -LiteralPath $source -PathType Leaf) {
            [void] (Copy-FilePreservingPath -Source $source -DestinationRoot $paths.exports -RelativePath $artifact.path)
            $copiedArtifacts += 1
        }
    }

    $bundlePath = Join-Path $paths.git "Option-Beacon-complete.bundle"
    $bundleCreate = Invoke-GitText -Arguments @("bundle", "create", $bundlePath, "--all") -AllowFailure
    if ($bundleCreate.ExitCode -ne 0) {
        Add-BackupError "Git bundle creation failed: $($bundleCreate.Text)"
    } else {
        $bundleVerify = Invoke-GitText -Arguments @("bundle", "verify", $bundlePath) -AllowFailure
        $gitBundleSucceeded = $bundleVerify.ExitCode -eq 0 -and (Test-Path -LiteralPath $bundlePath) -and (Get-Item $bundlePath).Length -gt 0
        [System.IO.File]::WriteAllText((Join-Path $paths.git "bundle-verification.txt"),
            (Protect-BackupText $bundleVerify.Text), (New-Object System.Text.UTF8Encoding($false)))
        if (-not $gitBundleSucceeded) { Add-BackupError "Git bundle verification failed." }
    }

    [System.IO.File]::WriteAllText((Join-Path $paths.git "working-tree-status.txt"), $statusText,
        (New-Object System.Text.UTF8Encoding($false)))
    [System.IO.File]::WriteAllText((Join-Path $paths.git "remotes.txt"), $remoteText,
        (New-Object System.Text.UTF8Encoding($false)))
    [System.IO.File]::WriteAllText((Join-Path $paths.git "branches.txt"), $branchesText,
        (New-Object System.Text.UTF8Encoding($false)))
    [System.IO.File]::WriteAllText((Join-Path $paths.git "tags.txt"), $tagsText,
        (New-Object System.Text.UTF8Encoding($false)))
    [System.IO.File]::WriteAllText((Join-Path $paths.git "working-tree.patch"),
        (Invoke-GitText -Arguments @("diff", "--binary", "HEAD")).Text,
        (New-Object System.Text.UTF8Encoding($false)))
    [System.IO.File]::WriteAllText((Join-Path $paths.git "staged.patch"),
        (Invoke-GitText -Arguments @("diff", "--binary", "--cached")).Text,
        (New-Object System.Text.UTF8Encoding($false)))

    $includedArtifactRecords = @($includedArtifacts | ForEach-Object { $_ })
    $excludedArtifactRecords = @($excludedArtifacts | ForEach-Object { $_ })
    Write-JsonUtf8 -Path (Join-Path $paths.manifests "secret_inventory.json") -Value $secretInventory
    Write-JsonUtf8 -Path (Join-Path $paths.manifests "untracked_included.json") -Value $includedArtifactRecords
    Write-JsonUtf8 -Path (Join-Path $paths.manifests "untracked_excluded.json") -Value $excludedArtifactRecords
    foreach ($template in @("backup.config.example.json", "frontend\.env.example")) {
        $source = Join-Path $repository $template
        if (Test-Path -LiteralPath $source -PathType Leaf) {
            [void] (Copy-FilePreservingPath -Source $source -DestinationRoot $paths.configuration -RelativePath $template)
        }
    }

    if ($configuration.ProtectedSecretsSource) {
        $protected = if ([System.IO.Path]::IsPathRooted($configuration.ProtectedSecretsSource)) {
            [System.IO.Path]::GetFullPath($configuration.ProtectedSecretsSource)
        } else {
            [System.IO.Path]::GetFullPath((Join-Path $repository $configuration.ProtectedSecretsSource))
        }
        if ((Test-Path -LiteralPath $protected -PathType Leaf) -and
            ([System.IO.Path]::GetExtension($protected).ToLowerInvariant() -in @(".age", ".gpg", ".pgp"))) {
            $protectedDirectory = Join-Path $paths.configuration "protected-secrets"
            New-Item -ItemType Directory -Path $protectedDirectory -Force | Out-Null
            Copy-Item -LiteralPath $protected -Destination (Join-Path $protectedDirectory ([System.IO.Path]::GetFileName($protected)))
            $protectedSecretsStatus = "encrypted-source-copied"
        } else {
            $protectedSecretsStatus = "configured-source-missing-or-not-approved-format"
            Add-BackupWarning "ProtectedSecretsSource must be an existing .age, .gpg, or .pgp file. Plaintext secrets were not copied."
        }
    } else {
        Add-BackupWarning "No portable encrypted secrets archive is configured. Credential names are inventoried, but values must come from a password manager or separately protected archive."
    }

    if (-not $databaseUrl) {
        $databaseStatus = "connection-not-configured"
        Add-BackupWarning "DATABASE_URL is not configured; no database dump was created."
    } elseif (-not $pgDump) {
        $databaseStatus = "pg_dump-not-found"
        Add-BackupWarning "pg_dump is not installed or configured; no database dump was created."
    } else {
        $versionResult = Invoke-DatabaseProcess -Executable $pgDump -Arguments "--version"
        $databaseVersion = ($versionResult.StandardOutput + $versionResult.StandardError).Trim()
        $dumpPath = Join-Path $paths.database "optionbeacon-postgresql.dump"
        $dumpArguments = "--format=custom --no-owner --no-acl --file=`"$dumpPath`""
        $dumpResult = Invoke-DatabaseProcess -Executable $pgDump -Arguments $dumpArguments -DatabaseUrl $databaseUrl
        if ($dumpResult.ExitCode -ne 0) {
            $databaseStatus = "pg_dump-failed"
            Add-BackupWarning "pg_dump failed: $($dumpResult.StandardError)"
        } elseif (-not (Test-Path -LiteralPath $dumpPath) -or (Get-Item $dumpPath).Length -le 0) {
            $databaseStatus = "empty-dump"
            Add-BackupWarning "pg_dump returned without a non-empty dump file."
        } else {
            $databaseSucceeded = $true
            $databaseStatus = "dump-created"
            $pgRestore = Get-ConfiguredExecutable -ConfiguredPath "" -CommandName "pg_restore"
            if ($pgRestore) {
                $restoreCheck = Invoke-DatabaseProcess -Executable $pgRestore -Arguments "--list `"$dumpPath`""
                if ($restoreCheck.ExitCode -eq 0 -and $restoreCheck.StandardOutput) {
                    $databaseVerification = "pg_restore-list-passed"
                } else {
                    $databaseSucceeded = $false
                    $databaseStatus = "restore-list-verification-failed"
                    $databaseVerification = "failed"
                    Add-BackupWarning "Database dump could not be verified with pg_restore --list."
                }
            } else {
                $databaseVerification = "non-empty-custom-dump"
                Add-BackupWarning "pg_restore was not available for deep dump verification; the custom dump is non-empty."
            }
        }
    }

    $recoveryFiles = @("RESTORE_OPTIONBEACON.md", "RECOVERY_CHECKLIST.md")
    foreach ($file in $recoveryFiles) {
        $source = Join-Path $repository $file
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
            Add-BackupError "Required recovery documentation is missing: $file"
        } else {
            Copy-Item -LiteralPath $source -Destination (Join-Path $paths.configuration $file) -Force
        }
    }

    $requiredSnapshotFiles = @(
        (Join-Path $paths.repository "requirements.txt"),
        (Join-Path $paths.repository "frontend\package.json"),
        (Join-Path $paths.repository "frontend\pnpm-lock.yaml"),
        (Join-Path $paths.configuration "RESTORE_OPTIONBEACON.md"),
        (Join-Path $paths.configuration "RECOVERY_CHECKLIST.md")
    )
    $dependencyFilesPresent = (@($requiredSnapshotFiles | Where-Object { Test-Path -LiteralPath $_ }).Count -eq $requiredSnapshotFiles.Count)
    $coreVerified = $repositoryCopySucceeded -and $gitBundleSucceeded -and $dependencyFilesPresent -and $script:Errors.Count -eq 0
    $finalState = Get-BackupFinalState -CoreVerified $coreVerified `
        -DatabaseRequired $configuration.DatabaseDumpRequired -DatabaseSucceeded $databaseSucceeded `
        -WarningCount $script:Warnings.Count -FatalErrorCount $script:Errors.Count

    $frontendManifestPresent = (Test-Path -LiteralPath (Join-Path $paths.repository "frontend\package.json")) -and
        (Test-Path -LiteralPath (Join-Path $paths.repository "frontend\pnpm-lock.yaml"))
    $statistics = Get-DirectoryStatistics $staging
    $manifest = [ordered] @{
        schema_version = 1
        backup_timestamp_utc = (Get-Date).ToUniversalTime().ToString("o")
        snapshot_name = $snapshotName
        host = [ordered] @{
            computer_name = $env:COMPUTERNAME
            os_version = [Environment]::OSVersion.VersionString
            powershell_version = $PSVersionTable.PSVersion.ToString()
        }
        source = [ordered] @{
            repository_path = $repository
            branch = $branch
            head = $head
            modified_tracked = @($status.ModifiedTracked)
            untracked_detected = @($status.Untracked)
        }
        destination = [ordered] @{
            volume_label = $destination.VolumeLabel
            detection = $destination.Detection
            backup_root = $backupRoot
        }
        git = [ordered] @{
            bundle_status = if ($gitBundleSucceeded) { "verified" } else { "failed" }
            tracked_working_tree_status = if ($repositoryCopySucceeded) { "copied" } else { "failed" }
            tracked_files_copied = $copiedTracked
            remotes_recorded = [bool] $remoteText
            branches_recorded = [bool] $branchesText
            tags_recorded = $true
        }
        database = [ordered] @{
            required = [bool] $configuration.DatabaseDumpRequired
            configured = [bool] $databaseUrl
            pg_dump_available = [bool] $pgDump
            version = $databaseVersion
            status = $databaseStatus
            verification = $databaseVerification
        }
        configuration = [ordered] @{
            status = $configurationStatus
            secret_backup_status = $protectedSecretsStatus
            secret_inventory_count = $secretInventory.Count
            plaintext_secrets_copied = $false
            frontend_manifest_status = if ($frontendManifestPresent) { "present" } else { "missing" }
        }
        exports = [ordered] @{
            copied = $copiedArtifacts
            included = $includedArtifactRecords
            excluded = $excludedArtifactRecords
        }
        verification = [ordered] @{
            destination_exists = (Test-Path -LiteralPath $staging)
            git_bundle_verified = $gitBundleSucceeded
            repository_snapshot_exists = (Test-Path -LiteralPath $paths.repository)
            dependency_manifests_present = $dependencyFilesPresent
            recovery_documentation_present = $dependencyFilesPresent
            database_dump_verified = $databaseSucceeded
            source_commit_recorded = [bool] $head
            final_state = $finalState
        }
        totals = [ordered] @{
            file_count = $statistics.file_count
            approximate_bytes = $statistics.bytes
        }
        warnings = @($script:Warnings | ForEach-Object { $_ })
        errors = @($script:Errors | ForEach-Object { $_ })
    }
    Write-JsonUtf8 -Path (Join-Path $paths.manifests "backup_manifest.json") -Value $manifest

    $summaryLines = @(
        "OptionBeacon Backup Summary",
        "===========================",
        "",
        "Result: $finalState",
        "Snapshot: $snapshotName",
        "Created (UTC): $($manifest.backup_timestamp_utc)",
        "Branch: $branch",
        "HEAD: $head",
        "Git bundle: $($manifest.git.bundle_status)",
        "Repository files copied: $copiedTracked",
        "Local artifacts copied: $copiedArtifacts",
        "Database: $databaseStatus",
        "Plaintext secrets copied: NO",
        "Warnings: $($script:Warnings.Count)",
        "Errors: $($script:Errors.Count)",
        "",
        "See manifests\backup_manifest.json and configuration\RESTORE_OPTIONBEACON.md."
    )
    [System.IO.File]::WriteAllLines((Join-Path $paths.manifests "BACKUP_SUMMARY.txt"), $summaryLines,
        (New-Object System.Text.UTF8Encoding($false)))

    $finalStatistics = Get-DirectoryStatistics $staging
    $manifest.totals.file_count = $finalStatistics.file_count
    $manifest.totals.approximate_bytes = $finalStatistics.bytes
    Write-JsonUtf8 -Path (Join-Path $paths.manifests "backup_manifest.json") -Value $manifest

    if (-not (Test-Path -LiteralPath (Join-Path $paths.manifests "backup_manifest.json")) -or
        -not (Test-Path -LiteralPath (Join-Path $paths.manifests "BACKUP_SUMMARY.txt"))) {
        throw "Manifest verification failed."
    }
    Move-Item -LiteralPath $staging -Destination $finalSnapshot
    $script:LogPath = Join-Path $finalSnapshot "logs\backup.log"

    foreach ($file in $recoveryFiles) {
        Copy-Item -LiteralPath (Join-Path $repository $file) -Destination (Join-Path $recoveryRoot $file) -Force
    }

    if ($finalState -in @("BACKUP SUCCESSFUL", "BACKUP SUCCESSFUL WITH WARNINGS")) {
        $latest = Join-Path $backupRoot "LATEST"
        if (-not (Test-Path -LiteralPath $latest)) { New-Item -ItemType Directory -Path $latest | Out-Null }
        Copy-Item -LiteralPath (Join-Path $finalSnapshot "manifests\backup_manifest.json") `
            -Destination (Join-Path $latest "backup_manifest.json") -Force
        Copy-Item -LiteralPath (Join-Path $finalSnapshot "manifests\BACKUP_SUMMARY.txt") `
            -Destination (Join-Path $latest "BACKUP_SUMMARY.txt") -Force
        [void] (Update-LatestPointer -BackupRoot $backupRoot -SnapshotName $snapshotName -FinalState $finalState)
    }

    Copy-Item -LiteralPath (Join-Path $finalSnapshot "logs\backup.log") `
        -Destination (Join-Path $globalLogsRoot "$snapshotName.log") -Force
    $snapshotDirectories = @(Get-ChildItem -LiteralPath $snapshotsRoot -Directory | Where-Object { $_.Name -notlike ".incomplete-*" })
    $allSnapshotFiles = @($snapshotDirectories | ForEach-Object { Get-ChildItem -LiteralPath $_.FullName -Recurse -File })
    $snapshotBytes = ($allSnapshotFiles | Measure-Object -Property Length -Sum).Sum
    if ($null -eq $snapshotBytes) { $snapshotBytes = 0 }

    Write-BackupMessage "" Gray
    Write-BackupMessage $finalState $(if ($finalState -eq "BACKUP PARTIAL") { "Yellow" } elseif ($finalState -eq "BACKUP FAILED") { "Red" } else { "Green" })
    Write-BackupMessage "Snapshot: $finalSnapshot" Gray
    Write-BackupMessage "Snapshots retained: $($snapshotDirectories.Count); total size: $([math]::Round($snapshotBytes / 1GB, 3)) GB" Gray
    if ($finalState -eq "BACKUP PARTIAL") { exit 2 }
    if ($finalState -eq "BACKUP FAILED") { exit 1 }
    exit 0
} catch {
    Add-BackupError $_.Exception.Message
    if ($_.ScriptStackTrace) {
        Add-BackupError "Failure location: $($_.ScriptStackTrace)"
    }
    Write-BackupMessage "BACKUP FAILED" Red
    Write-BackupMessage "An incomplete staging directory was retained for diagnosis: $staging" Yellow
    exit 1
}

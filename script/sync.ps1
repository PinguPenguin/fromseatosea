#Hey there future reviewer; this was generated using an LLM, but has been manually tweaked.
param(
    [switch]$DryRun,
    [switch]$PreferNewer
)

$repoRoot = (& git -C $PSScriptRoot rev-parse --show-toplevel 2>$null).Trim()

if (-not $repoRoot) {
    Write-Error "Could not find a Git repository above: $PSScriptRoot"
    exit 1
}

$modRoot      = Join-Path $repoRoot "mod"
$parallelRoot = Join-Path $repoRoot "parallelchanges"

if (-not (Test-Path -LiteralPath $modRoot)) {
    Write-Error "Mod folder not found: $modRoot"
    exit 1
}

if (-not (Test-Path -LiteralPath $parallelRoot)) {
    Write-Error "Parallelchanges folder not found: $parallelRoot"
    exit 1
}

function Get-ChangedEntries {
    param(
        [string]$RepoRoot,
        [string]$TopFolder
    )

    $lines = & git -C $RepoRoot status --porcelain=v1 --untracked-files=all -- $TopFolder 2>$null

    if ($LASTEXITCODE -ne 0) {
        Write-Error "Git status failed for $TopFolder"
        exit 1
    }

    $entries = @{}

    foreach ($line in $lines) {
        if ([string]::IsNullOrWhiteSpace($line)) {
            continue
        }

        $status = $line.Substring(0, 2)
        $pathPart = $line.Substring(3)

        # Handle rename lines: old -> new
        if ($pathPart -like "* -> *") {
            $pathPart = ($pathPart -split " -> ", 2)[1]
        }

        $gitPath = $pathPart.Trim('"') -replace '/', '\'
        $prefix = "$TopFolder\"

        if (-not $gitPath.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            continue
        }

        $relativePath = $gitPath.Substring($prefix.Length)

        $entries[$relativePath] = [PSCustomObject]@{
            Status = $status
            GitPath = $gitPath
        }
    }

    return $entries
}

function Get-FileHashSafe {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $null
    }

    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
}

function Copy-OneWay {
    param(
        [string]$SourceFile,
        [string]$DestFile,
        [string]$Label
    )

    $destDir = Split-Path -Parent $DestFile

    Write-Host $Label

    if (-not $DryRun) {
        New-Item -ItemType Directory -Path $destDir -Force | Out-Null
        Copy-Item -LiteralPath $SourceFile -Destination $DestFile -Force
    }
}

$modChanges      = Get-ChangedEntries -RepoRoot $repoRoot -TopFolder "mod"
$parallelChanges = Get-ChangedEntries -RepoRoot $repoRoot -TopFolder "parallelchanges"

$allRelativePaths = New-Object System.Collections.Generic.HashSet[string]
foreach ($k in $modChanges.Keys) { [void]$allRelativePaths.Add($k) }
foreach ($k in $parallelChanges.Keys) { [void]$allRelativePaths.Add($k) }

if ($allRelativePaths.Count -eq 0) {
    Write-Host "No changed files found under mod or parallelchanges."
    exit 0
}

$copiedToMod = 0
$copiedToParallel = 0
$conflicts = @()
$skippedDeletes = 0
$skippedMissing = 0
$identicalBothChanged = 0

Write-Host "Repo root:        $repoRoot"
Write-Host "Mod:              $modRoot"
Write-Host "Parallelchanges:  $parallelRoot"
Write-Host ""

foreach ($relativePath in ($allRelativePaths | Sort-Object)) {
    $modEntry = $modChanges[$relativePath]
    $parEntry = $parallelChanges[$relativePath]

    $modFile = Join-Path $modRoot $relativePath
    $parFile = Join-Path $parallelRoot $relativePath

    $modExists = Test-Path -LiteralPath $modFile -PathType Leaf
    $parExists = Test-Path -LiteralPath $parFile -PathType Leaf

    $modDeleted = $false
    $parDeleted = $false

    if ($modEntry -and $modEntry.Status.Contains("D")) { $modDeleted = $true }
    if ($parEntry -and $parEntry.Status.Contains("D")) { $parDeleted = $true }

    # Safety: do not mirror deletions automatically
    if ($modDeleted -or $parDeleted) {
        Write-Host "[SKIP-DEL] $relativePath"
        $skippedDeletes++
        continue
    }

    # Changed only in parallelchanges -> copy to mod
    if ($parEntry -and -not $modEntry) {
        if (-not $parExists) {
            Write-Host "[SKIP-MISS] parallelchanges\$relativePath"
            $skippedMissing++
            continue
        }

        $label = if ($modExists) { "[PAR -> MOD] update $relativePath" } else { "[PAR -> MOD] new    $relativePath" }
        Copy-OneWay -SourceFile $parFile -DestFile $modFile -Label $label
        $copiedToMod++
        continue
    }

    # Changed only in mod -> copy to parallelchanges
    if ($modEntry -and -not $parEntry) {
        if (-not $modExists) {
            Write-Host "[SKIP-MISS] mod\$relativePath"
            $skippedMissing++
            continue
        }

        $label = if ($parExists) { "[MOD -> PAR] update $relativePath" } else { "[MOD -> PAR] new    $relativePath" }
        Copy-OneWay -SourceFile $modFile -DestFile $parFile -Label $label
        $copiedToParallel++
        continue
    }

    # Changed in both
    if ($modEntry -and $parEntry) {
        if (-not $modExists -or -not $parExists) {
            Write-Host "[SKIP-MISS] $relativePath"
            $skippedMissing++
            continue
        }

        $modHash = Get-FileHashSafe -Path $modFile
        $parHash = Get-FileHashSafe -Path $parFile

        if ($modHash -eq $parHash) {
            Write-Host "[BOTH SAME] $relativePath"
            $identicalBothChanged++
            continue
        }

        if ($PreferNewer) {
            $modTime = (Get-Item -LiteralPath $modFile).LastWriteTimeUtc
            $parTime = (Get-Item -LiteralPath $parFile).LastWriteTimeUtc

            if ($modTime -ge $parTime) {
                Copy-OneWay -SourceFile $modFile -DestFile $parFile -Label "[CONFLICT -> MOD WINS] $relativePath"
                $copiedToParallel++
            }
            else {
                Copy-OneWay -SourceFile $parFile -DestFile $modFile -Label "[CONFLICT -> PAR WINS] $relativePath"
                $copiedToMod++
            }
        }
        else {
            Write-Host "[CONFLICT] $relativePath"
            $conflicts += $relativePath
        }
    }
}

Write-Host ""
Write-Host "Done."
Write-Host "Copied into mod:              $copiedToMod"
Write-Host "Copied into parallelchanges:  $copiedToParallel"
Write-Host "Both changed but identical:   $identicalBothChanged"
Write-Host "Skipped deletions:            $skippedDeletes"
Write-Host "Skipped missing files:        $skippedMissing"
Write-Host "Conflicts:                    $($conflicts.Count)"

if ($conflicts.Count -gt 0) {
    Write-Host ""
    Write-Host "Conflicting files:"
    foreach ($c in $conflicts) {
        Write-Host "  $c"
    }
    Write-Host ""
    Write-Host "Re-run with -PreferNewer to auto-resolve conflicts by last modified time."
}

if ($DryRun) {
    Write-Host ""
    Write-Host "Dry run only: no files were copied."
}
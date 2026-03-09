#Hey there future reviewer; this was generated using an LLM, but has been manually tweaked.
param(
    [switch]$DryRun
)

$repoRoot = (& git -C $PSScriptRoot rev-parse --show-toplevel 2>$null).Trim()

if (-not $repoRoot) {
    Write-Error "Could not find a Git repository above: $PSScriptRoot"
    exit 1
}

$sourceRoot = Join-Path $repoRoot "parallelchanges"
$destRoot   = Join-Path $repoRoot "mod"

if (-not (Test-Path -LiteralPath $sourceRoot)) {
    Write-Error "Source folder not found: $sourceRoot"
    exit 1
}

if (-not (Test-Path -LiteralPath $destRoot)) {
    Write-Error "Destination folder not found: $destRoot"
    exit 1
}

$gitLines = & git -C $repoRoot status --porcelain=v1 --untracked-files=all -- "parallelchanges" 2>$null

if ($LASTEXITCODE -ne 0) {
    Write-Error "Git status failed."
    exit 1
}

if (-not $gitLines -or $gitLines.Count -eq 0) {
    Write-Host "No changed files found under parallelchanges."
    exit 0
}

$newCount = 0
$updatedCount = 0
$skippedDeletedCount = 0
$skippedMissingCount = 0

Write-Host "Repo root:    $repoRoot"
Write-Host "Source:       $sourceRoot"
Write-Host "Destination:  $destRoot"
Write-Host ""

foreach ($line in $gitLines) {
    if ([string]::IsNullOrWhiteSpace($line)) {
        continue
    }

    $status = $line.Substring(0, 2)
    $pathPart = $line.Substring(3)

    if ($status.Contains("D")) {
        Write-Host "[SKIP-DEL] $pathPart"
        $skippedDeletedCount++
        continue
    }

    if ($pathPart -like "* -> *") {
        $pathPart = ($pathPart -split " -> ", 2)[1]
    }

    $gitPath = $pathPart.Trim('"') -replace '/', '\'

    if (-not $gitPath.StartsWith("parallelchanges\")) {
        continue
    }

    $relativePath = $gitPath.Substring("parallelchanges\".Length)
    $sourceFile = Join-Path $sourceRoot $relativePath
    $destFile   = Join-Path $destRoot $relativePath
    $destDir    = Split-Path -Parent $destFile

    if (-not (Test-Path -LiteralPath $sourceFile -PathType Leaf)) {
        Write-Host "[SKIP-MISS] $relativePath"
        $skippedMissingCount++
        continue
    }

    $isNew = -not (Test-Path -LiteralPath $destFile -PathType Leaf)

    if ($isNew) {
        Write-Host "[NEW]      $relativePath"
        $newCount++
    }
    else {
        Write-Host "[UPDATED]  $relativePath"
        $updatedCount++
    }

    if (-not $DryRun) {
        New-Item -ItemType Directory -Path $destDir -Force | Out-Null
        Copy-Item -LiteralPath $sourceFile -Destination $destFile -Force
    }
}

Write-Host ""
Write-Host "Done."
Write-Host "New files copied:       $newCount"
Write-Host "Modified files copied:  $updatedCount"
Write-Host "Skipped deletions:      $skippedDeletedCount"
Write-Host "Skipped missing source: $skippedMissingCount"

if ($DryRun) {
    Write-Host ""
    Write-Host "Dry run only: no files were copied."
}
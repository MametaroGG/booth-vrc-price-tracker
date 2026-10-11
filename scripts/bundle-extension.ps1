# BOOTH Price Tracker for VRChat - Extension Bundler
$SourceDir = "extension"
$OutputDir = "dist"
$Version = (Get-Content "$SourceDir/manifest.json" -Raw | ConvertFrom-Json).version
$ZipFile = "boopa-v$Version-chrome-web-store.zip"

# Create output directory if it doesn't exist
if (!(Test-Path $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir
}

# Remove old zip if exists
if (Test-Path "$OutputDir\$ZipFile") {
    Remove-Item "$OutputDir\$ZipFile"
}

Write-Host "Bundling extension files..." -ForegroundColor Cyan

# Files to include (explicitly)
$FilesToInclude = @(
    "manifest.json",
    "background.js",
    "content.js",
    "content.css",
    "icon16.png",
    "icon48.png",
    "icon128.png"
)

# Create temporary folder for bundling
$TempDir = "temp_bundle"
if (Test-Path $TempDir) { Remove-Item -Recurse -Force $TempDir }
New-Item -ItemType Directory -Path $TempDir

foreach ($file in $FilesToInclude) {
    if (Test-Path "$SourceDir\$file") {
        Copy-Item "$SourceDir\$file" "$TempDir\$file"
        Write-Host "  Included: $file"
    }
    else {
        throw "Required extension file missing: $file"
    }
}

# Create ZIP
Compress-Archive -Path "$TempDir\*" -DestinationPath "$OutputDir\$ZipFile" -Force

# Cleanup
Remove-Item -Recurse -Force $TempDir

Write-Host "`nSuccess! Bundle created at: $OutputDir\$ZipFile" -ForegroundColor Green

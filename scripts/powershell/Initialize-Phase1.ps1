# Phase 1 — Walking Skeleton Implementation Package

## 🚀 Quick Setup Script (PowerShell)

Save as `Initialize-Phase1.ps1` and run from repo root:

```powershell
# Initialize-Phase1.ps1
Write-Host "🚀 Initializing Phase 1 - Walking Skeleton" -ForegroundColor Cyan

# Create directory structure
$dirs = @(
    "src/data_quality_toolkit/shared"
    "src/data_quality_toolkit/utils"
    "src/data_quality_toolkit/loaders/file"
    "src/data_quality_toolkit/profiling/core"
    "src/data_quality_toolkit/assessment"
    "src/data_quality_toolkit/exporters/filesystem"
    "src/data_quality_toolkit/exporters/bi/templates"
    "src/data_quality_toolkit/workflow"
    "src/data_quality_toolkit/cli"
    "tests/unit"
    "tests/integration"
    "tests/fixtures"
    "dist/star"
    "dist/powerbi_package"
)

foreach ($dir in $dirs) {
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
    Write-Host "  ✓ Created $dir" -ForegroundColor Green
}

# Create __init__.py files
$initPaths = @(
    "src/data_quality_toolkit/shared"
    "src/data_quality_toolkit/utils"
    "src/data_quality_toolkit/loaders"
    "src/data_quality_toolkit/loaders/file"
    "src/data_quality_toolkit/profiling"
    "src/data_quality_toolkit/profiling/core"
    "src/data_quality_toolkit/assessment"
    "src/data_quality_toolkit/exporters"
    "src/data_quality_toolkit/exporters/filesystem"
    "src/data_quality_toolkit/exporters/bi"
    "src/data_quality_toolkit/workflow"
    "src/data_quality_toolkit/cli"
)

foreach ($path in $initPaths) {
    New-Item -ItemType File -Path "$path/__init__.py" -Force | Out-Null
}

Write-Host "`n✅ Phase 1 directory structure created!" -ForegroundColor Green
Write-Host "📝 Now copy the implementation files below into their respective locations" -ForegroundColor Yellow

# Initialize-Phase2.ps1
Write-Host "🚀 Initializing Phase 2 - Zero-Config Power BI" -ForegroundColor Cyan

$dirs = @(
    "src/data_quality_toolkit/exporters/bi/powerbi_zero_config"
    "src/data_quality_toolkit/exporters/bi/templates"
    "src/data_quality_toolkit/exporters/time"
    "dist/powerbi_package/time"
    "dist/powerbi_package/star"
    "dist/powerbi_package/dax"
    "dist/time"
)

foreach ($dir in $dirs) {
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
    Write-Host "  ✓ Created $dir" -ForegroundColor Green
}

# Create __init__.py files
$initPaths = @(
    "src/data_quality_toolkit/exporters/time"
    "src/data_quality_toolkit/exporters/bi/powerbi_zero_config"
)

foreach ($path in $initPaths) {
    New-Item -ItemType File -Path "$path/__init__.py" -Force | Out-Null
}

Write-Host "`n✅ Phase 2 directory structure created!" -ForegroundColor Green

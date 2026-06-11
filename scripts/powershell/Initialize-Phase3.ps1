# Initialize-Phase3.ps1
Write-Host "🚀 Initializing Phase 3 - Semantics/KPIs" -ForegroundColor Cyan

$dirs = @(
    "src/data_quality_toolkit/semantics"
    "dist/powerbi_package/dax"
    "dist/semantics"
    "semantics"
    "tests/golden"
    "tests/unit/semantics"
)

foreach ($dir in $dirs) {
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
    Write-Host "  ✓ Created $dir" -ForegroundColor Green
}

Write-Host "`n✅ Phase 3 directory structure created!" -ForegroundColor Green

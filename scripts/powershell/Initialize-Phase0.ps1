<#
Initialize-Phase0.ps1 (fixed)
- Creates Phase 0 structure & stub files if missing
- Optional cleanup of items not on whitelist (never touches .git/)
- Defaults to Dry-Run (preview). Use -Apply to execute. Add -Aggressive to clean inside whitelisted dirs.
#>

[CmdletBinding()]
param(
  [switch]$Apply,
  [switch]$Aggressive,
  [switch]$IncludeOptional,  # LICENSE/SECURITY.md/CONTRIBUTING.md/CODEOWNERS/config/
  [switch]$IncludeInfra,     # infra/monitoring (docs-only skeleton)
  [string[]]$Preserve = @(".git", ".gitignore", ".editorconfig", ".pre-commit-config.yaml", ".env", ".venv", "venv", ".vscode")
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ----------------------- Helpers -----------------------

function New-DirIfMissing {
  param([string]$Path)
  if ([string]::IsNullOrWhiteSpace($Path)) { return }  # guard root files
  if (-not (Test-Path -LiteralPath $Path)) {
    if ($Apply) { New-Item -ItemType Directory -Path $Path | Out-Null }
    Write-Host "DIR  : $Path" -ForegroundColor Cyan
  }
}

function New-FileIfMissing {
  param([string]$Path, [string]$Content = "")
  if (-not (Test-Path -LiteralPath $Path)) {
    $parent = Split-Path -Parent $Path
    New-DirIfMissing -Path $parent
    if ($Apply) { $Content | Out-File -FilePath $Path -Encoding UTF8 -Force }
    Write-Host "FILE : $Path" -ForegroundColor Cyan
  }
}

function Write-FileIfMissingOrEmpty {
  param([string]$Path, [string]$Content)
  if (-not (Test-Path -LiteralPath $Path)) {
    New-FileIfMissing -Path $Path -Content $Content
  } else {
    $size = (Get-Item -LiteralPath $Path).Length
    if ($size -eq 0) {
      if ($Apply) { $Content | Out-File -FilePath $Path -Encoding UTF8 -Force }
      Write-Host "FILL : $Path (was empty)" -ForegroundColor Yellow
    }
  }
}

function Join-Rel([string]$p) { return (Join-Path -Path (Get-Location) -ChildPath $p) }

# ---------------- Phase-0 structure --------------------

$dirs = @(
  "src/data_quality_toolkit",
  "tests",
  "docs/powerbi",
  "examples",
  "scripts",
  ".github/workflows"
)

$infraDirs = @("infra/monitoring")  # optional

$rootFiles = @{
  "pyproject.toml" = @"
[project]
name = "data-quality-toolkit"
version = "0.0.0"
description = "Data Quality toolkit with zero-config Power BI, semantic KPIs, and LLM insights."
readme = "README.md"
requires-python = ">=3.12"
license = { text = "TBD (MIT/Apache-2.0)" }
authors = [{ name = "Your Team" }]

[project.scripts]
dqt = "data_quality_toolkit.cli.main:app"  # implemented in later phases

dependencies = [
  "pandas",
  "fastapi",
  "uvicorn",
  "pydantic",
  "typing-extensions",
  "python-dotenv",
  "jinja2",
  "typer",
  "packaging",
  "streamlit",
  "lorax-client"
]

[project.optional-dependencies]
dev = ["pytest", "pytest-cov", "ruff", "mypy"]

[tool.ruff]
line-length = 100
select = ["E","F","I","UP","B"]
ignore = ["E501"]
target-version = "py311"

[tool.mypy]
python_version = "3.12"
warn_unused_ignores = true
disallow_any_generics = true
no_implicit_optional = true
strict_optional = true

[tool.pytest.ini_options]
addopts = "-q"
testpaths = ["tests"]
"@

  ".gitignore" = @"
# Python
__pycache__/
*.py[cod]
*.pyo
*.pyd
*.pkl
.mypy_cache/
.ruff_cache/
.pytest_cache/

# Build/Dist
build/
dist/
*.egg-info/

# IDE
.vscode/
.idea/

# Data/Artifacts (allow examples/)
*.csv
*.parquet
*.xlsx
!examples/*.csv
export/
powerbi_package/
logs/
*.log
*.db
*.sqlite

# Env & secrets
.env
secrets.toml
"@

  ".env.example" = @"
# LLM / SSOT
LORAX_BASE_URL=http://localhost:8080
LORAX_TIMEOUT_SECS=30

# Engine limits
MAX_ROWS_IN_MEMORY=1000000
SAMPLE_SIZE=10000

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=json

# Export / BI
EXPORT_BASE_DIR=./dist
PBI_BASE_FOLDER_PARAMETER=./dist

# Security switches (never commit real secrets)
DQT_ALLOW_NETWORK=false
"@

  "Makefile" = @"
# Phase 0 placeholders — describe targets; implement commands in Phase 1+
install:
	@echo ""TODO (Phase 1): venv + pip install""

lint:
	@echo ""TODO (Phase 1): ruff check""

type:
	@echo ""TODO (Phase 1): mypy src/""

test:
	@echo ""TODO (Phase 1): pytest -q --maxfail=1""

build-pbi:
	@echo ""TODO (Phase 2/3): build powerbi package""

demo:
	@echo ""TODO (later): run end-to-end demo""

clean:
	@echo ""TODO (Phase 1): rm -rf build/ dist/ .pytest_cache/ .mypy_cache/ .ruff_cache/""
"@

  "README.md" = @"
# Data Quality Toolkit (MVP)

**What**: End-to-end data quality pipeline → zero-config Power BI package, semantic KPI layer, LLM-powered insights.
**Who**: Data/BI/Analytics engineers.

## Status
Phase 0 (repo + config scaffolding) — logic-only.

## Quickstart (Phase 0)
\`\`\`bash
make install
make lint
make type
make test
\`\`\`

## Roadmap
- Phase 1: CSV → Profile → Assess → Star CSV
- Phase 2: Zero-config Power BI package
- Phase 3: Semantic KPIs (DAG → DAX)
- Phase 4: RLS & Incremental Refresh
- Phase 5+: Telemetry, Interfaces, Hardening

See docs/powerbi/ for guide stubs. Security policy in SECURITY.md (once added).
"@

  ".editorconfig" = @"
root = true

[*]
charset = utf-8
end_of_line = lf
indent_style = space
indent_size = 4
insert_final_newline = true
trim_trailing_whitespace = true
"@

  ".pre-commit-config.yaml" = @"
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.6.2
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.10.0
    hooks:
      - id: mypy
        additional_dependencies: []
"@

  "constraints.txt" = @"
# Optional: pin transitive dependencies for reproducible builds.
# Example:
# pandas==2.2.2
# fastapi==0.110.0
"@
}

$optionalRootFiles = @{
  "LICENSE" = "TBD — choose MIT or Apache-2.0 and replace this placeholder."
  "SECURITY.md" = "# Security Policy`n`nReport vulnerabilities via GitHub Security Advisories. Do not include sensitive data in issues."
  "CONTRIBUTING.md" = "# Contributing`n`nUse Conventional Commits. PRs require green CI (lint/type/tests)."
  "CODEOWNERS" = "# Set code owners per path`n* @your-team"
}

$docFiles = @{
  "docs/powerbi/date_table.md" = "# Date Table Guide`n`n- Required fields: date, time_id (YYYYMMDD), year, month, week_iso, dow_iso, is_weekend."
  "docs/powerbi/incremental_refresh.md" = "# Incremental Refresh`n`n- Parameters: RangeStart, RangeEnd."
  "docs/powerbi/rls_testing.md" = "# RLS Testing`n`n- Use 'View as' to validate OwnerOnly and DatasetScope roles."
}

$scriptFiles = @{
  "scripts/generate_dim_time.py" = "# Placeholder: will generate dim_time.csv (Phase 2)."
  "scripts/export_star_schema.py" = "# Placeholder: will export star schema CSVs (Phase 1/2)."
  "scripts/build_powerbi_template.py" = "# Placeholder: will assemble Power BI package (Phase 2)."
  "scripts/validate_kpis.py" = "# Placeholder: will validate kpi_catalog.yaml DAG (Phase 3)."
}

$exampleFiles = @{
  "examples/README.md" = "# Examples`n`n- 01_quickstart.ipynb will be added in later phases."
  "examples/01_quickstart.ipynb" = @"
{
  ""cells"": [],
  ""metadata"": { ""language_info"": { ""name"": ""python"" } },
  ""nbformat"": 4,
  ""nbformat_minor"": 5
}
"@
}

$ciFiles = @{
  ".github/workflows/ci.yml" = @"
name: CI (Phase 0 skeleton)
on: [push, pull_request]
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      # TODO: add ruff
  type:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      # TODO: add mypy
  unit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      # TODO: add pytest
  e2e:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      # TODO: add minimal e2e
  build-pbi:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      # TODO: add package build
"@
  ".github/workflows/release.yml" = @"
name: Release (Phase 0 skeleton)
on:
  push:
    tags:
      - 'v*.*.*'
jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      # TODO: build & attach artifacts
"@
}

$infraFiles = @{
  "infra/monitoring/README.md" = "# Monitoring (placeholder)`n`nWill document Prometheus/Grafana wiring once telemetry lands."
}

# ---------------- Create structure --------------------

foreach ($d in $dirs) { New-DirIfMissing -Path $d }
if ($IncludeInfra) {
  foreach ($d in $infraDirs) { New-DirIfMissing -Path $d }
}

foreach ($kv in $rootFiles.GetEnumerator())   { Write-FileIfMissingOrEmpty -Path $kv.Key -Content $kv.Value }
foreach ($kv in $docFiles.GetEnumerator())    { Write-FileIfMissingOrEmpty -Path $kv.Key  -Content $kv.Value }
foreach ($kv in $scriptFiles.GetEnumerator()) { Write-FileIfMissingOrEmpty -Path $kv.Key -Content $kv.Value }
foreach ($kv in $exampleFiles.GetEnumerator()){ Write-FileIfMissingOrEmpty -Path $kv.Key -Content $kv.Value }
foreach ($kv in $ciFiles.GetEnumerator())     { Write-FileIfMissingOrEmpty -Path $kv.Key  -Content $kv.Value }

if ($IncludeOptional) {
  foreach ($kv in $optionalRootFiles.GetEnumerator()) { Write-FileIfMissingOrEmpty -Path $kv.Key -Content $kv.Value }
  New-DirIfMissing -Path "config"
  New-FileIfMissing -Path "config/README.md" -Content "# Config samples (Phase 1+)"
}

if ($IncludeInfra) {
  foreach ($kv in $infraFiles.GetEnumerator()) { Write-FileIfMissingOrEmpty -Path $kv.Key -Content $kv.Value }
}

# ---------------- Build whitelist ---------------------

# Use a case-insensitive HashSet of absolute paths
$whitelist = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)

foreach ($p in @(".git") + $Preserve) { $null = $whitelist.Add((Join-Rel $p)) }

# Required dirs
$allDirs = @()
$allDirs += $dirs
if ($IncludeInfra) { $allDirs += $infraDirs }
foreach ($d in $allDirs) { $null = $whitelist.Add((Join-Rel $d)) }

# Required files
$allFiles = @()
$allFiles += $rootFiles.Keys
$allFiles += $docFiles.Keys
$allFiles += $scriptFiles.Keys
$allFiles += $exampleFiles.Keys
$allFiles += $ciFiles.Keys
if ($IncludeOptional) { $allFiles += $optionalRootFiles.Keys + @("config","config/README.md") }
foreach ($f in $allFiles) { $null = $whitelist.Add((Join-Rel $f)) }

# ----------------- Cleanup phase ----------------------

Write-Host ""
if (-not $Apply) {
  Write-Host "Dry-run: no deletions will occur. Use -Apply to execute." -ForegroundColor Yellow
}

function Is-Whitelisted([IO.FileSystemInfo]$item) {
  $full = $item.FullName
  foreach ($w in $whitelist) {
    if ($full -ieq $w) { return $true }
  }
  return $false
}

# Top-level clean
$rootItems = Get-ChildItem -LiteralPath (Get-Location) -Force | Where-Object { $_.Name -notin @(".","..") }
foreach ($it in $rootItems) {
  if ($it.Name -ieq ".git") { continue }
  if (Is-Whitelisted $it) { continue }

  # If it's inside a whitelisted dir, skip (Aggressive pass handles sub-items)
  $underKnown = $false
  foreach ($w in $whitelist) {
    if ((Test-Path $w) -and (Get-Item $w).PSIsContainer) {
      if ($it.FullName -like (Join-Path $w "*")) { $underKnown = $true; break }
    }
  }
  if (-not $underKnown) {
    $msg = "CLEAN: remove top-level '$($it.Name)'"
    if ($Apply) {
      if ($it.PSIsContainer) { Remove-Item -LiteralPath $it.FullName -Recurse -Force }
      else { Remove-Item -LiteralPath $it.FullName -Force }
      Write-Host "$msg  [done]" -ForegroundColor Magenta
    } else {
      Write-Host "$msg  [dry-run]" -ForegroundColor DarkMagenta
    }
  }
}

# Aggressive: clean inside whitelisted directories
if ($Aggressive) {
  foreach ($w in $whitelist) {
    if (-not (Test-Path $w)) { continue }
    $item = Get-Item $w -ErrorAction SilentlyContinue
    if ($null -eq $item -or -not $item.PSIsContainer) { continue }

    $children = Get-ChildItem -LiteralPath $w -Recurse -Force | Where-Object { $_.Name -notin @(".","..") }
    foreach ($child in $children) {
      if ($child.FullName -like "*\.git*") { continue }
      if (Is-Whitelisted $child) { continue }
      $basename = Split-Path -Leaf $child.FullName
      if ($Preserve -contains $basename) { continue }

      $rel = $child.FullName.Substring((Get-Location).Path.Length).TrimStart('\','/')
      $msg = "CLEAN: remove unknown inside '$rel'"
      if ($Apply) {
        try {
          if ($child.PSIsContainer) { Remove-Item -LiteralPath $child.FullName -Recurse -Force }
          else { Remove-Item -LiteralPath $child.FullName -Force }
          Write-Host "$msg  [done]" -ForegroundColor Magenta
        } catch {
          Write-Host "SKIP : $msg  [$_]" -ForegroundColor DarkYellow
        }
      } else {
        Write-Host "$msg  [dry-run]" -ForegroundColor DarkMagenta
      }
    }
  }
}

Write-Host ""
Write-Host ("Phase 0 scaffold " + ($(if ($Apply) { "APPLIED" } else { "PREVIEWED" }))) -ForegroundColor Green
Write-Host ("Aggressive clean: " + ($(if ($Aggressive) { "ON" } else { "OFF" }))) -ForegroundColor Green

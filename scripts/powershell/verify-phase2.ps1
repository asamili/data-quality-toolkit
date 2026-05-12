# scripts/powershell/verify-phase2.ps1
$ErrorActionPreference = "Stop"

Write-Host "🔍 Verifying Phase 2 installation..."

# --- Python launcher ---
$PY = $null; $PY_ARGS = @()
if (Get-Command python -ErrorAction SilentlyContinue) { $PY = "python" }
elseif (Get-Command py -ErrorAction SilentlyContinue) { $PY = "py"; $PY_ARGS = @("-3") }
else { throw "Python not found on PATH (tried 'python' and 'py')." }

function Invoke-PythonCode([string]$code) {
  & $PY @PY_ARGS "-c" $code
  if ($LASTEXITCODE -ne 0) { throw "Python snippet failed (exit $LASTEXITCODE)" }
}

function Run-Checked([string]$exe, [string[]]$argv) {
  & $exe @argv
  if ($LASTEXITCODE -ne 0) {
    throw "Command failed: $exe $($argv -join ' ') (exit $LASTEXITCODE)"
  }
}

# --- Dependencies ---
Invoke-PythonCode @'
import importlib, sys
mods = ["jinja2","pandas","pydantic"]
for m in mods:
    try:
        mod = importlib.import_module(m)
        ver = getattr(mod, "__version__", "")
        print(("✓ %s %s" % (m, ver)).strip())
    except Exception as e:
        print("✗ %s not installed: %s" % (m, e), file=sys.stderr); sys.exit(1)
'@

# --- Build demo (Phase 1 + 2) ---
Write-Host "`n📊 Running Phase 1 + 2 demo..."
$built = $false
if (Get-Command make -ErrorAction SilentlyContinue) {
  try {
    Run-Checked make @("clean")
    Run-Checked make @("demo-pbi")
    $built = $true
    Write-Host "✓ Built with make targets"
  } catch {
    Write-Warning "make failed, falling back to CLI: $($_.Exception.Message)"
  }
}

if (-not $built) {
  if (-not (Test-Path test.csv)) {
    "id,name,score`n1,Alice,95`n2,Bob,87`n3,Charlie,76" | Set-Content -Encoding utf8 test.csv
  }
  if (Get-Command dqt -ErrorAction SilentlyContinue) {
    Run-Checked dqt @("export","test.csv")
    Run-Checked dqt @("build-pbi","--star","dist/star","--out","dist/powerbi_package")
  } else {
    Run-Checked $PY ($PY_ARGS + @("-m","data_quality_toolkit.cli.main","export","test.csv"))
    Run-Checked $PY ($PY_ARGS + @("-m","data_quality_toolkit.cli.main","build-pbi","--star","dist/star","--out","dist/powerbi_package"))
  }
}

$pkg = "dist/powerbi_package"
if (-not (Test-Path $pkg)) { throw "Package folder missing: $pkg (build step failed)" }

Write-Host "`n📁 Checking outputs..."
$hasModel   = Test-Path "$pkg/model.pbit"
$hasReadme  = Test-Path "$pkg/model.pbit.README"

if ($hasModel) {
  Write-Host "✓ model.pbit present"
} elseif ($hasReadme) {
  Write-Host "ℹ model.pbit missing (placeholder). See model.pbit.README for how to add your template."
} else {
  Write-Warning "No model.pbit present. That's fine for validation; you just can't open in Desktop until you add a real template."
}

foreach ($f in @("parameters.json","relationships.json")) {
  if (-not (Test-Path "$pkg/$f")) { throw "$f missing" } else { Write-Host "✓ $f exists" }
}
if (-not (Test-Path "$pkg/time/dim_time.csv")) { throw "time/dim_time.csv missing" } else { Write-Host "✓ time/dim_time.csv exists" }

# --- Validate package ---
Write-Host "`n🧪 Validating package..."
Invoke-PythonCode @'
from pathlib import Path
import json, sys
from data_quality_toolkit.exporters.bi.powerbi_zero_config.packager import validate_package
pkg = Path("dist/powerbi_package")
res = validate_package(pkg)
print(json.dumps(res, indent=2))
sys.exit(0 if res.get("valid") else 1)
'@


Write-Host "`n✅ Phase 2 verification complete!"

function Get-TemplatesPath {
  # 1) repo-relative (two levels up from this script)
  $repoTpl = Join-Path $PSScriptRoot "..\..\src\data_quality_toolkit\exporters\bi\powerbi_zero_config\templates"
  if (Test-Path $repoTpl) { return (Resolve-Path $repoTpl).Path }

  # 2) installed package location (ask Python)
  try {
    $out = & $PY @PY_ARGS "-c" @'
import importlib.resources as ir, os
import data_quality_toolkit.exporters.bi.powerbi_zero_config as pkg
p = ir.files(pkg) / "templates"
print(os.fspath(p))
'@
    if ($LASTEXITCODE -eq 0 -and $out) {
      $p = $out.Trim()
      if (Test-Path $p) { return (Resolve-Path $p).Path }
    }
  } catch { }

  return $null
}

$tpl = Get-TemplatesPath
Write-Host "Open in Desktop only if you have a real template:"
if ($tpl) {
  Write-Host "  $tpl\model.pbit"
} else {
  Write-Host "  (templates folder not found automatically)"
  Write-Host "  If installed via pip, look under your Python site-packages for:"
  Write-Host "    ...\data_quality_toolkit\exporters\bi\powerbi_zero_config\templates\model.pbit"
}

Write-Host "Then re-run: dqt build-pbi --star dist/star --out dist/powerbi_package"
Write-Host "When opening, set BaseFolder to the ABSOLUTE path of ./dist:"
Write-Host ("  " + (Resolve-Path "dist").Path)

# Security Policy

## Reporting a Vulnerability

**Do not create a public GitHub issue for security vulnerabilities.**

Use [GitHub Security Advisories](../../security/advisories/new) to report privately.

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix, if known

### Response timeline

| Action | Target |
|--------|--------|
| Initial acknowledgment | Within 72 hours |
| Severity assessment | Within 1 week |

| Severity | Target fix timeline |
|----------|---------------------|
| Critical | 1–3 days |
| High | 1 week |
| Medium | 2 weeks |
| Low | Next release |

---

## What DQT does with your data

- All processing is local. No data is sent to external services during normal operation.
- Input files are read from disk and processed in memory.
- Output artifacts (`quality_report.json`, CSV star-schema files) are written only to the directory you specify with `--outdir`.
- No telemetry, no hidden caches, no network calls.

### Current limitations relevant to security

DQT does **not** currently include:

- PII detection or masking
- Authentication or authorization
- API endpoints
- Encryption of output files
- Compliance controls (GDPR, HIPAA, SOC 2, etc.)

Do not use DQT as a security control or compliance enforcement tool. If your input data is sensitive, treat your `--outdir` output directory as equally sensitive — it contains column-level profiling statistics derived from the input.

---

## Best practices

- Do not commit `.env` files or credentials to source control.
- Use a virtual environment. Do not install as root.
- Review output files before sharing — `fact_quality_metrics.csv` and `fact_issues.csv` reflect the structure and statistics of your input data.
- Pin dependency versions in production environments.

---

## Path, output, and network stance

DQT is a **local, single-user CLI**. It trusts the paths you pass it:

- **Input paths** (`csv` argument) are validated only for existence and a `.csv` suffix. They are not sandboxed — DQT reads whatever local path the invoking user supplies. Do not run DQT against paths you do not control.
- **Output paths** are, for most commands, written verbatim to the location you specify: `--outdir` (`profile`, `assess`, `export`, `export-star`, `compare`) and the Power BI / KPI / time-dimension `--out` targets receive no scope or traversal guarding, by design; the invoking user is responsible for the target directory. The exceptions are the DuckDB, Excel, and PNG drift exporters (`dqt drift-history export-duckdb` / `export-xlsx` / `export-plots`) and the Streamlit UI export and Power BI package surfaces, which validate their target through `shared/path_guard` — it rejects `..` traversal and a symlink that escapes the resolved parent directory.
- **Network**: off by default. The `DQT_ALLOW_NETWORK` flag defaults to `false` and no code path performs outbound calls during profiling, assessment, or export.
- **Credentials**: DQT reads none. No setting holds a secret, so `dqt settings show` cannot echo one; this is pinned by `tests/unit/security/test_security_surface.py`. An `api_key` / `API_KEY` setting existed in earlier versions and has been removed — setting that variable in the environment now has no effect on DQT.

These are deliberate boundaries for a local tool, not gaps. Treat input and output directories as equally sensitive (see above).

---

## Security tooling

"Enforced" below means the check runs automatically and fails the commit or the build.
Configuration alone, a listed dependency, or a manually runnable tool is not enforcement.

**Enforced on every commit and every CI run** (`.pre-commit-config.yaml`; CI also runs
`pre-commit run --all-files`):

- **Ruff "S" rules** — flake8-bandit lint rules, part of the standard `ruff check`.
- **Ruff "C90" / mccabe** — cyclomatic complexity ceiling (`max-complexity = 10`) to bound function complexity.
- black, isort, mypy, and a focused pytest run.

**Enforced in CI only** (`.github/workflows/ci.yml`):

- **pip-audit** — dependency CVE scanning. CI runs `pip-audit --desc` as a **blocking** gate, so the build fails on a known CVE. Acting on reported CVEs (dependency upgrades) is handled in a dedicated dependency gate.
- **import-linter** — the architecture and containment contracts declared in `pyproject.toml`.
- **pytest** — the full suite, including the tested invariants listed below.

**Configured but not enforced — manual, opt-in only:**

- **Bandit** (`-ll -iii -r src/`) — static security analysis of source. Configured in `.pre-commit-config.yaml` on the `manual` stage, so it does **not** run on a routine commit and is **not** part of any CI workflow. Run it deliberately: `pre-commit run bandit --hook-stage manual`.
- **pip-audit** is additionally available as a manual local hook (`pre-commit run pip-audit --hook-stage manual`); the enforced execution is the CI one above.

**Not configured in this repository:** secret scanning, container image scanning, and any
dependency or static-analysis scanner other than those named above. No such tool is
configured or executed anywhere in the repository. The release workflow
(`.github/workflows/release.yml`) gates on lint, type checking, and the test suite only —
it runs no scanner, including pip-audit.

**Tested security invariants** — protected by the normal pytest suite rather than by a
scanner:

- Output-path containment and symlink-escape rejection — `tests/unit/shared/test_path_guard.py`.
- Human-facing path redaction — `tests/unit/shared/test_text_redaction.py`, `tests/unit/cli/test_cli_path_redaction.py`, `tests/unit/ui/test_error_redaction.py`.
- Webhook SSRF guard — `tests/unit/notifications/test_webhook.py`.
- Import and layer containment — `tests/unit/architecture/test_import_boundary_contracts.py`, `tests/unit/ui/test_ui_layer_containment.py`.

---

## Supported versions

| Version | Supported          |
|---------|--------------------|
| 2.10.x  | Yes                |
| 2.9.x   | Yes                |
| < 2.9   | Not actively supported |

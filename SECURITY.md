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
- **Output paths** (`--out` / `--outdir`) are written verbatim to the location you specify. DQT performs no scope or traversal guarding on output, by design; the invoking user is responsible for the target directory.
- **Network**: off by default. The `DQT_ALLOW_NETWORK` flag defaults to `false` and no code path performs outbound calls during profiling, assessment, or export. Secrets such as `API_KEY` are read from the environment only and are never written to output artifacts.

These are deliberate boundaries for a local tool, not gaps. Treat input and output directories as equally sensitive (see above).

---

## Security tooling

The repository enforces security and complexity checks in pre-commit and CI:

- **Bandit** (`-ll -iii -r src/`) — static security analysis of source.
- **Ruff "S" rules** — flake8-bandit lint rules on every check.
- **Ruff "C90" / mccabe** — cyclomatic complexity ceiling (`max-complexity = 10`) to bound function complexity.
- **pip-audit** — dependency CVE scanning. Runs in CI as an advisory step (`pip-audit --desc`, non-blocking) and is available as a manual pre-commit hook (`pre-commit run pip-audit --hook-stage manual`). Acting on reported CVEs (dependency upgrades) is handled in a dedicated dependency gate.

---

## Supported versions

| Version | Supported          |
|---------|--------------------|
| 2.1.x   | Yes                |
| < 2.1   | Not actively supported |

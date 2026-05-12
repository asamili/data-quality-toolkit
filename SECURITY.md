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

DQT v1.2.0 does **not** include:

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

## Supported versions

| Version | Supported |
|---------|-----------|
| 1.2.x   | Yes       |
| < 1.2   | No        |

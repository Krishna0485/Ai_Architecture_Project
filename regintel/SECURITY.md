# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 1.x     | yes       |
| < 1.0   | no        |

## Reporting a vulnerability

Please **do not open a public issue**. Use GitHub's private vulnerability reporting
("Security" tab -> "Report a vulnerability") with:

- affected component and version / commit,
- reproduction steps or a proof of concept,
- impact (e.g. cross-tenant data access, prompt-injection bypass, secret exposure).

You will get an acknowledgement within 72 hours and a remediation plan within 14 days.

## Scope highlights

In scope: tenant isolation, authentication/authorisation, prompt-injection defences, PII
handling, MCP tool security, supply chain (dependencies, images).

The threat model, controls and known limitations are documented in
[docs/security.md](docs/security.md).

## Practices in this repository

- gitleaks in pre-commit and CI; no secrets in code or prompts (`.env` is git-ignored).
- Dependabot for Python, GitHub Actions and Docker; CodeQL analysis; Trivy image scans.
- Non-root containers, read-only root filesystems and network policies in the Helm chart.

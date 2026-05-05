# Security Policy

## Supported versions

cascade is pre-1.0 and only the latest minor receives security updates.

| Version | Supported          |
| ------- | ------------------ |
| 0.x     | :white_check_mark: |

## Reporting a vulnerability

Please **do not** file public GitHub issues for security reports.

Email: `ag.chaudhari.1512@gmail.com` with the subject line
`[security] cascade: <short description>`.

Include:

- Affected versions
- Reproduction steps or proof of concept
- Impact assessment
- Suggested mitigation if you have one

You will receive an acknowledgement within 72 hours. We aim to triage within five working
days and to ship a fix or mitigation within 30 days for high-severity issues.

## Scope

In scope:

- The `cascade` Python package
- The MCP server (`cascade.mcp`)
- The FastAPI service (`cascade.api`)
- Default Docker images published from this repository

Out of scope:

- Third-party dependencies (please report upstream)
- Self-hosted deployments where the operator has modified configuration
- Issues requiring privileged access on the host
- Social engineering, denial of service via volume

## Disclosure

We follow coordinated disclosure. Once a fix is released, we publish a GitHub Security
Advisory crediting the reporter unless anonymity is requested.

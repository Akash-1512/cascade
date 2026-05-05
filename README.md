# cascade

> An open-source OKR governance platform with multi-agent AI coaching and organizational memory that survives turnover.

[![CI](https://github.com/Akash-1512/cascade/actions/workflows/ci.yml/badge.svg)](https://github.com/Akash-1512/cascade/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

## What this is

cascade helps teams that already run OKRs do three things existing tools don't:

1. **Draft sharper OKRs** — a multi-agent loop critiques drafts against measurability, ambition, and alignment before they're committed.
2. **Remember the *why*** — every state-changing decision (objective committed, target lowered, KR closed) is captured with the alternatives considered and the tradeoff accepted. The reasoning survives reorgs and turnover.
3. **Coach in-flow** — check-ins, retros, and risk reviews happen as conversations, with traces that managers can audit.

cascade exposes its capabilities over the **Model Context Protocol**, so the same data is queryable from Claude Desktop, Cursor, or any MCP-aware client.

## Status

Pre-release. See [CHANGELOG.md](CHANGELOG.md) for the roadmap to v1.0.

## Documentation

- [Architecture overview](docs/architecture/overview.md)
- [Agent design](docs/architecture/agents.md)
- [Memory layer](docs/architecture/memory.md)
- [Architecture Decision Records](docs/adr/)
- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md)

## License

MIT — see [LICENSE](LICENSE).

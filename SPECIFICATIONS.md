# Boulder Specifications

Boulder is a web-based editor and simulator for Cantera ReactorNet systems. This document is the
specifications index for Boulder. See individual linked documents for normative details.

## STONE — YAML Configuration Format

**STONE** (Structured Type-Oriented Network Expressions) is the YAML dialect Boulder uses to
describe reactor networks. **[STONE_SPECIFICATIONS.md](STONE_SPECIFICATIONS.md)** is the normative
contract for STONE v2, the current authored format.

Key points:

- STONE v2 uses `network:` (single stage) or `stages:` + dynamic stage blocks (multi-stage).
- No version header is required; Boulder detects the dialect automatically.
- STONE v1 files (top-level `nodes:` / `connections:` / `groups:`) are rejected.
- See `configs/README.md` for worked examples.

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full system architecture, including the config
pipeline, API layer, plugin system, staged solver, and frontend.

## Agents / Development

See [AGENTS.md](AGENTS.md) for development conventions, test commands, and coding guidelines for
contributors and AI agents.

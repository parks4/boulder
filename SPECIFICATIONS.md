# Boulder Specifications

Boulder is a web-based editor and simulator for Cantera ReactorNet systems. This document is the
specifications index for Boulder. See individual linked documents for normative details.

## STONE — YAML Configuration Format

**STONE** (Structured Type-Oriented Network Expressions) is the YAML dialect Boulder uses to
describe reactor networks. **[STONE_SPECIFICATIONS.md](STONE_SPECIFICATIONS.md)** is the normative
contract for STONE 2.x, the current authored format.

Key points:

- STONE 2.x ("v2") uses `network:` (single stage) or `stages:` + dynamic stage blocks (multi-stage).
- Files carry `metadata.stone_version: "MAJOR.MINOR"`, versioned independently of the Boulder
  package version: MINOR bumps when the format last changed vocabulary or semantics. Files without
  it are older 2.x files: Boulder loads them and stamps the current version on save
  (STONE_SPECIFICATIONS.md §1).
- Within a MAJOR, newer Boulder reads every older file; removed keys are migrated with a warning.
- STONE 1.x ("v1") files (top-level `nodes:` / `connections:` / `groups:`) are rejected.
- See `configs/README.md` for worked examples.

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full system architecture, including the config
pipeline, API layer, plugin system, staged solver, and frontend.

## Agents / Development

See [AGENTS.md](AGENTS.md) for development conventions, test commands, and coding guidelines for
contributors and AI agents.

## Frontend UI/UX

Detailed frontend behaviour specifications (graph layout, edge styles, P&ID conventions, panel
behaviour) live in **[frontend/SPECIFICATIONS.md](frontend/SPECIFICATIONS.md)**.

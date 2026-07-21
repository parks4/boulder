# CLAUDE.md

Read [AGENTS.md](AGENTS.md) first — it is the canonical contributor and agent guide for this
repository (project layout, environment setup, verification commands, coding conventions, PR
requirements). Follow it for all work in this repo.

## Never name a host package in Boulder's own repo

Boulder is a generic, host-agnostic STONE engine — other packages (plugin entry points,
`BOULDER_PLUGINS`) extend it without Boulder's core knowing what they are. Never mention a
specific host/consumer package by name (e.g. "Bloc", "BlocConverter") anywhere in this repo:
source comments, docstrings, test names/bodies, commit messages, or PR titles/descriptions.
Describe them generically instead — "a host", "an external plugin package", "a host's converter
subclass". This applies even when the change was motivated by, or verified against, one specific
host's code — the motivation can live in your own working notes, not in what gets committed here.

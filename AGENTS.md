# AGENTS.md — Boulder contributor and agent guide

This file is for human contributors and AI coding agents working on **Boulder** (Cantera ReactorNet visualizer: FastAPI backend + React/Vite frontend).

## Project layout

| Area | Path |
|------|------|
| Python package | `boulder/` |
| HTTP API | `boulder/api/main.py`, `boulder/api/routes/` |
| CLI | `boulder/cli.py` |
| Frontend | `frontend/src/` |
| STONE YAML examples | `configs/` — see `configs/README.md` |
| Vendored Cantera `.py` samples | `docs/cantera_examples/` — see `docs/cantera_upstream_examples.rst` |
| Tests | `tests/` — see `tests/README.md` |
| Sphinx docs | `docs/` |
| Examples | `examples/` (including `plugin_example.py`) |

Deep-dive architecture: [ARCHITECTURE.md](ARCHITECTURE.md).

## Custom plugins and downstream code

- **By default**, specific custom plugins and derivative works **must not** be mentioned in
  Boulder's source, tests, or docs. Contributors and agents should not add names, imports,
  links, or optional dependencies that tie core Boulder to a particular downstream package.
- **Boulder does not have to** reference or accommodate any given custom plugin in-tree.
  Extensions belong in separate packages and load through the public hooks (entry points
  `boulder.plugins`, `BOULDER_PLUGINS`, etc.) described in [ARCHITECTURE.md](ARCHITECTURE.md).
- Exceptions only when a **maintainer explicitly** asks to document or wire a named
  integration in this repository.

## Environment

1. Create and activate the **boulder** conda environment (includes Node for frontend work):

   ```bash
   conda env create -n boulder -f environment.yml
   conda activate boulder
   pip install -e .
   ```

1. Build the production frontend when you change UI code:

   ```bash
   cd frontend
   npm ci   # or npm install
   npm run build
   ```

## Verification (what to run before a PR)

From the repo root **with conda `boulder` active**:

```bash
make unit-tests COV_REPORT=xml   # or html locally
make type-check
make qa                           # pre-commit on all files
```

Optional docs:

```bash
make docs-build
```

Frontend (matches CI):

```bash
cd frontend && npm ci && npm run test:unit && npm run type-check && npm run build
```

Windows: install `make` or run the equivalent commands from the [Makefile](Makefile).

### Targeted tests (recent architecture)

After touching runner, staged networks, unfold/composite reactors, or plugins:

```bash
python -m pytest tests/test_runner.py tests/test_unfold.py tests/test_plugin_example.py -vv
```

## Coding conventions (.cursorrules + tooling)

- **Line length**: keep lines under **110** characters where practical (Ruff pycodestyle max is aligned with this).
- **Exceptions**: do not blanket `try`/`except`; catch specific exceptions only. Prefer clear errors over silent fixes.
- **Python**: Python **3.11**; typing via **mypy** strict (`pyproject.toml` / `Makefile` `type-check`).
- **Lint / style**: **Ruff** (numpy docstring convention; see `pyproject.toml`).
- **Type coverage**: backend changes should pass `make type-check`.

## Testing conventions

- **TDD mindset**: prefer writing or extending tests that lock behavior before large refactors.
- **Fix the library**, not tests, when behavior is wrong — unless the test was genuinely wrong.
- **No mock-only tests**; integration-style / real behavior is preferred.
- **Docstrings**: every test should state **what is asserted** (including E2E).
- Run the full backend suite when feasible: `make unit-tests`.

## Frontend

- Always **`npm run build`** in `frontend/` after substantive UI changes (per team rules).
- Dev flow: `boulder --dev` or backend + `npm run dev` (Vite proxies `/api`; see README).

## Git and releases

- **Do not commit** unless the user or maintainer explicitly asks (team rule for agents).
- GitHub Releases: workflow [.github/workflows/release.yml](.github/workflows/release.yml) builds wheel and sdist with full git history (`setuptools_scm`).

## License

This project is licensed under the MIT License; see the [LICENSE](LICENSE) file in the repository root.

## Further reading

- [README.md](README.md) — install, CLI, dev mode.
- [ARCHITECTURE.md](ARCHITECTURE.md) — systems design, plugins, staged solve, API.
- [configs/README.md](configs/README.md) — STONE YAML.
- [docs/usage.rst](docs/usage.rst) — Sphinx usage and plugin pointers.

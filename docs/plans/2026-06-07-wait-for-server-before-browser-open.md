# Wait for Server Before Browser Open — Boulder Implementation Plan

> **For agent:** Use `@executing-plans` task-by-task. Use `@verification-before-completion` before claiming done.

**Goal:** Fix the Boulder CLI opening the browser before uvicorn binds port 8050, which causes Firefox "Unable to connect" on first load.

**Architecture:** Add small port-polling helpers in `boulder/cli.py`, reusing existing `is_port_in_use()`. Start a daemon thread that polls until the backend port is bound, then call `webbrowser.open()`. Apply the same pattern in `--dev` mode for the Vite port (5173) instead of a fixed 5 s sleep.

**Tech Stack:** Python 3, uvicorn, FastAPI, pytest, threading

**Repo:** Boulder (`boulder/boulder/cli.py`)

**Reference:** `sda/dashboard/app.py` — `_wait_and_open()` (poll until port bound, then open browser)

______________________________________________________________________

## Background

### Root cause

In `boulder/boulder/cli.py` (~664–670), production mode calls `webbrowser.open(url)` **before** `uvicorn.run()`:

```python
    url = f"http://{args.host}:{args.port}"
    if not args.no_open:
        # Open browser slightly before server starts; browser will retry the connection
        try:
            webbrowser.open(url)
        except Exception:
            pass
```

The comment assumes the browser will retry. Firefox often does not — you get "Unable to connect" on `127.0.0.1:8050`.

In `--dev` mode (~521–537), a fixed `time.sleep(5)` before opening Vite is brittle (too short on slow machines, wasteful on fast ones).

### Success criteria

1. Browser opens only after the target port is bound (or timeout fallback).
1. `--no-open` still suppresses browser open.
1. `--dev` polls port 5173 instead of sleeping 5 s.
1. New unit tests cover helpers; existing CLI tests pass.
1. Manual smoke test: `boulder` loads without "Unable to connect".

### Port detection note

`is_port_in_use(host, port)` returns `False` when the port is free, `True` when something is listening. Poll until it returns `True`.

______________________________________________________________________

## Task 1: Extract port-wait helpers

**Files:**

- Modify: `boulder/boulder/cli.py` (after `find_available_port`, ~line 47)
- Create: `boulder/tests/test_cli_browser.py`

**Step 1: Write failing tests**

Create `tests/test_cli_browser.py` with tests for `wait_for_port` and `schedule_browser_open`.

**Step 2: Run tests — expect FAIL**

```bash
pytest tests/test_cli_browser.py -v
```

Expected: `ImportError: cannot import name 'wait_for_port'`

**Step 3: Implement helpers in `boulder/cli.py`**

Add `wait_for_port` and `schedule_browser_open` after `find_available_port`.

**Step 4: Run tests — expect PASS**

```bash
pytest tests/test_cli_browser.py -v
```

______________________________________________________________________

## Task 2: Wire production mode

**Files:**

- Modify: `boulder/boulder/cli.py` (~664–670)

Replace immediate `webbrowser.open()` with `schedule_browser_open()`.

______________________________________________________________________

## Task 3: Improve `--dev` mode

**Files:**

- Modify: `boulder/boulder/cli.py` (~521–537)

Replace fixed `time.sleep(5)` with `schedule_browser_open()` polling port 5173.

______________________________________________________________________

## Task 4: Final verification

```bash
pytest tests/test_cli_browser.py tests/test_cli_import.py tests/test_cli_headless.py -v
python -c "from boulder.cli import wait_for_port, schedule_browser_open; print('ok')"
```

______________________________________________________________________

## Agent constraints

| Do | Don't |
|----|-------|
| Fix only in `boulder/boulder/cli.py` + new tests | Refactor uvicorn to subprocess |
| Keep `--no-open` behavior | Block `main()` waiting for browser |
| Use daemon threads | Add HTTP health polling unless port polling fails in practice |
| Run pytest before claiming done | Commit or push unless explicitly asked |

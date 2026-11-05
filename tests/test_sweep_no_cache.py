"""``--sweep --headless --no-cache`` sets the variable before the sweep starts."""

from __future__ import annotations

import os
from pathlib import Path

from boulder import cli, sweep_runner


def test_no_cache_is_set_before_the_sweep_starts(tmp_path: Path, monkeypatch) -> None:
    """``BOULDER_NO_CACHE`` is ``"1"`` in the environment when the sweep is launched."""
    monkeypatch.setenv("BOULDER_NO_CACHE", "")  # restored on teardown
    seen: dict[str, str | None] = {}

    def fake_run(path, **kwargs):
        seen["value"] = os.environ.get("BOULDER_NO_CACHE")
        return path

    monkeypatch.setattr(sweep_runner, "run", fake_run)
    cfg = tmp_path / "config.yaml"
    cfg.write_text("network: []\n", encoding="utf-8")
    try:
        cli.main([str(cfg), "--sweep", "--headless", "--no-cache"])
    except SystemExit as exc:
        assert exc.code == 0
    assert seen["value"] == "1"

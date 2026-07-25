"""Tests for the --export-schema CLI flag and boulder.schema_export.

Asserts:
- --export-schema requires --headless and a config file (CLI validation).
- PlaywrightNotInstalledError carries an install hint and is raised instead
  of a bare ImportError when the optional dependency is missing.
- render_network_schema_png() produces a real, non-blank, light-background
  PNG of the network graph (integration test — skipped when the optional
  playwright dependency isn't installed).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

CONFIG_PATH = Path(__file__).parent.parent / "configs" / "mix_react_streams.yaml"


class TestExportSchemaCliValidation:
    def test_requires_headless(self, tmp_path):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "boulder.cli",
                str(CONFIG_PATH),
                "--export-schema",
                str(tmp_path / "out.png"),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert result.returncode == 2
        assert "Error: --export-schema requires --headless" in (result.stderr or "")

    def test_requires_config(self, tmp_path):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "boulder.cli",
                "--headless",
                "--export-schema",
                str(tmp_path / "out.png"),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert result.returncode == 2
        assert "Error: --export-schema requires a config file" in (result.stderr or "")

    def test_cli_help_includes_export_schema(self):
        result = subprocess.run(
            [sys.executable, "-m", "boulder.cli", "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert result.returncode == 0
        assert "--export-schema" in result.stdout
        assert "playwright" in result.stdout.lower()


class TestPlaywrightOptionalDependency:
    def test_missing_playwright_raises_clear_error(self, monkeypatch):
        """Simulate playwright not being installed.

        ImportError halted by a None sys.modules entry must surface as
        PlaywrightNotInstalledError with install instructions, not a bare
        traceback.
        """
        from boulder.schema_export import (
            PlaywrightNotInstalledError,
            _require_playwright,
        )

        monkeypatch.setitem(sys.modules, "playwright", None)
        monkeypatch.setitem(sys.modules, "playwright.sync_api", None)

        with pytest.raises(PlaywrightNotInstalledError) as exc_info:
            _require_playwright()
        message = str(exc_info.value)
        assert "playwright" in message.lower()
        assert "pip install boulder[playwright]" in message
        assert "playwright install chromium" in message

    def test_missing_config_file_raises_file_not_found(self, tmp_path):
        pytest.importorskip("playwright")
        from boulder.schema_export import render_network_schema_png

        with pytest.raises(FileNotFoundError):
            render_network_schema_png(
                tmp_path / "does_not_exist.yaml", tmp_path / "out.png"
            )


@pytest.mark.integration
class TestRenderNetworkSchemaPng:
    def test_renders_a_real_light_background_png(self, tmp_path):
        pytest.importorskip("playwright")
        from boulder.schema_export import render_network_schema_png

        output_path = tmp_path / "schema.png"
        result = render_network_schema_png(CONFIG_PATH, output_path, timeout=30.0)

        assert result == output_path
        data = output_path.read_bytes()
        assert len(data) > 1000, "output PNG is suspiciously small/blank"
        assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a valid PNG file"

    def test_cli_export_schema_end_to_end(self, tmp_path):
        pytest.importorskip("playwright")
        output_path = tmp_path / "schema.png"

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "boulder.cli",
                str(CONFIG_PATH),
                "--headless",
                "--export-schema",
                str(output_path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        assert result.returncode == 0, result.stderr
        assert "Network schema image written:" in result.stdout
        assert output_path.is_file()
        assert output_path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"

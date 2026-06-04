"""Tests for the CanteraScriptEmitter class and script_lines_for_runner.

Covers:
- Class existence and importability from boulder.download_script_emitter
- __init__ accepts optional ``converter`` kwarg stored as self.converter
- ``emit(config)`` returns the same lines as the backward-compat wrapper
  ``emit_cantera_native_script(config)``
- Backward-compat wrapper ``emit_cantera_native_script`` still works
- ``script_lines_for_runner`` is importable from boulder.download_script_emitter
  and returns a list of strings
"""

from __future__ import annotations

from typing import Any, Dict

_MINIMAL_CONFIG: Dict[str, Any] = {
    "phases": {"gas": {"mechanism": "gri30.yaml"}},
    "nodes": [
        {
            "id": "r1",
            "type": "IdealGasConstPressureMoleReactor",
            "properties": {
                "temperature": 1500,
                "pressure": 101325,
                "composition": "H2:1",
            },
        }
    ],
    "connections": [],
    "stages": [
        {
            "id": "s1",
            "nodes": ["r1"],
            "solver": {"kind": "advance_to_steady_state"},
        }
    ],
}


class TestCanteraScriptEmitterClass:
    """Verify CanteraScriptEmitter class structure and basic behaviour."""

    def test_class_is_importable(self):
        """CanteraScriptEmitter can be imported from boulder.download_script_emitter."""
        from boulder.download_script_emitter import CanteraScriptEmitter  # noqa: F401

    def test_class_is_callable(self):
        """CanteraScriptEmitter() can be instantiated with no arguments."""
        from boulder.download_script_emitter import CanteraScriptEmitter

        emitter = CanteraScriptEmitter()
        assert emitter is not None

    def test_init_accepts_converter_kwarg(self):
        """__init__ accepts optional converter=None and stores it as self.converter."""
        from boulder.download_script_emitter import CanteraScriptEmitter

        sentinel = object()
        emitter = CanteraScriptEmitter(converter=sentinel)
        assert emitter.converter is sentinel

    def test_init_converter_defaults_to_none(self):
        """Converter defaults to None when not supplied."""
        from boulder.download_script_emitter import CanteraScriptEmitter

        emitter = CanteraScriptEmitter()
        assert emitter.converter is None

    def test_emit_returns_list_of_strings(self):
        """emit(config) returns a non-empty list of strings."""
        from boulder.download_script_emitter import CanteraScriptEmitter

        lines = CanteraScriptEmitter().emit(_MINIMAL_CONFIG)
        assert isinstance(lines, list)
        assert len(lines) > 0
        assert all(isinstance(line, str) for line in lines)

    def test_emit_output_matches_backward_compat_wrapper(self):
        """emit(config) produces identical output to emit_cantera_native_script(config)."""
        from boulder.download_script_emitter import (
            CanteraScriptEmitter,
            emit_cantera_native_script,
        )

        class_lines = CanteraScriptEmitter().emit(_MINIMAL_CONFIG)
        wrapper_lines = emit_cantera_native_script(_MINIMAL_CONFIG)
        assert class_lines == wrapper_lines

    def test_emit_contains_cantera_import(self):
        """Emitted script starts with 'import cantera as ct'."""
        from boulder.download_script_emitter import CanteraScriptEmitter

        lines = CanteraScriptEmitter().emit(_MINIMAL_CONFIG)
        assert "import cantera as ct" in lines


class TestBackwardCompatWrapper:
    """Verify emit_cantera_native_script still works after the refactor."""

    def test_wrapper_still_importable(self):
        """emit_cantera_native_script is importable from boulder.download_script_emitter."""
        from boulder.download_script_emitter import (
            emit_cantera_native_script,  # noqa: F401
        )

    def test_wrapper_returns_list(self):
        """emit_cantera_native_script returns a list of strings."""
        from boulder.download_script_emitter import emit_cantera_native_script

        lines = emit_cantera_native_script(_MINIMAL_CONFIG)
        assert isinstance(lines, list)
        assert len(lines) > 0

    def test_wrapper_accepts_converter_class_arg(self):
        """emit_cantera_native_script accepts converter_class kwarg without error."""
        from boulder.download_script_emitter import emit_cantera_native_script

        lines = emit_cantera_native_script(
            _MINIMAL_CONFIG, converter_class="SomeConverter"
        )
        assert isinstance(lines, list)


class TestScriptLinesForRunner:
    """Verify script_lines_for_runner is importable as a module-level function."""

    def test_function_is_importable(self):
        """script_lines_for_runner can be imported from boulder.download_script_emitter."""
        from boulder.download_script_emitter import (
            script_lines_for_runner,  # noqa: F401
        )

    def test_function_returns_list(self):
        """script_lines_for_runner returns a non-empty list of strings.

        Called with a runner_import, runner_class, config_path, and plan=None.
        """
        from boulder.download_script_emitter import script_lines_for_runner

        result = script_lines_for_runner(
            runner_import="from boulder.runner import BoulderRunner",
            runner_class="BoulderRunner",
            config_path="/tmp/test.yaml",
            plan=None,
        )
        assert isinstance(result, list)
        assert len(result) > 0
        assert all(isinstance(line, str) for line in result)

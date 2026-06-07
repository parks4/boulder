"""Tests for SCRIPT_EMITTER_CLASS dispatch on DualCanteraConverter.

Asserts:
- DualCanteraConverter has a SCRIPT_EMITTER_CLASS class attribute equal to CanteraScriptEmitter
- _script_lines_for_cantera is an instance method (not a staticmethod)
- Subclassing DualCanteraConverter and setting SCRIPT_EMITTER_CLASS to a custom emitter
  causes _script_lines_for_cantera to return the custom emitter's output (virtual dispatch)
"""

from __future__ import annotations

from typing import Any, Dict, List

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


class TestScriptEmitterClassAttribute:
    """Verify SCRIPT_EMITTER_CLASS is set correctly on DualCanteraConverter."""

    def test_script_emitter_class_attribute_exists(self):
        """DualCanteraConverter has a SCRIPT_EMITTER_CLASS class attribute."""
        from boulder.cantera_converter import DualCanteraConverter

        assert hasattr(DualCanteraConverter, "SCRIPT_EMITTER_CLASS")

    def test_script_emitter_class_is_cantera_script_emitter(self):
        """DualCanteraConverter.SCRIPT_EMITTER_CLASS is CanteraScriptEmitter."""
        from boulder.cantera_converter import DualCanteraConverter
        from boulder.download_script_emitter import CanteraScriptEmitter

        assert DualCanteraConverter.SCRIPT_EMITTER_CLASS is CanteraScriptEmitter

    def test_script_lines_for_cantera_is_instance_method(self):
        """_script_lines_for_cantera is a regular instance method, not a staticmethod."""
        import inspect

        from boulder.cantera_converter import DualCanteraConverter

        # A staticmethod bound on the class would not have __self__ when fetched
        # via the instance. The simplest check: the unbound descriptor on the class
        # must NOT be a staticmethod.
        assert not isinstance(
            inspect.getattr_static(DualCanteraConverter, "_script_lines_for_cantera"),
            staticmethod,
        )


class TestScriptEmitterClassDispatch:
    """Verify virtual dispatch: subclass with custom SCRIPT_EMITTER_CLASS returns custom output."""

    def test_subclass_emitter_is_used(self):
        """Subclassing DualCanteraConverter with a custom SCRIPT_EMITTER_CLASS.

        Asserts that _script_lines_for_cantera delegates to the custom emitter,
        not the default one.
        """
        from boulder.cantera_converter import DualCanteraConverter
        from boulder.download_script_emitter import CanteraScriptEmitter

        SENTINEL = "# CUSTOM_EMITTER_SENTINEL"

        class SentinelEmitter(CanteraScriptEmitter):
            def emit(self, config: Dict[str, Any]) -> List[str]:
                return [SENTINEL]

        class CustomConverter(DualCanteraConverter):
            SCRIPT_EMITTER_CLASS = SentinelEmitter

        converter = CustomConverter()
        result = converter._script_lines_for_cantera(
            "from boulder.cantera_converter import DualCanteraConverter",
            "DualCanteraConverter",
            _MINIMAL_CONFIG,
        )
        assert result == [SENTINEL], f"Expected [{SENTINEL!r}], got {result!r}"

    def test_default_emitter_returns_real_script(self):
        """Default emitter produces a real Cantera-native script.

        Asserts that DualCanteraConverter._script_lines_for_cantera with its
        default SCRIPT_EMITTER_CLASS returns a non-empty list of strings.
        """
        from boulder.cantera_converter import DualCanteraConverter

        converter = DualCanteraConverter()
        result = converter._script_lines_for_cantera(
            "from boulder.cantera_converter import DualCanteraConverter",
            "DualCanteraConverter",
            _MINIMAL_CONFIG,
        )
        assert isinstance(result, list)
        assert len(result) > 0
        assert all(isinstance(line, str) for line in result)

    def test_emitter_receives_converter_instance(self):
        """The emitter receives the calling converter instance.

        Asserts that the emitter is instantiated with converter=self (the
        DualCanteraConverter instance), so emitter.converter is the converter
        that called _script_lines_for_cantera.
        """
        from boulder.cantera_converter import DualCanteraConverter
        from boulder.download_script_emitter import CanteraScriptEmitter

        captured = {}

        class CapturingEmitter(CanteraScriptEmitter):
            def emit(self, config: Dict[str, Any]) -> List[str]:
                captured["converter"] = self.converter
                return ["# captured"]

        class CapturingConverter(DualCanteraConverter):
            SCRIPT_EMITTER_CLASS = CapturingEmitter

        converter = CapturingConverter()
        converter._script_lines_for_cantera("", "", _MINIMAL_CONFIG)

        assert captured.get("converter") is converter

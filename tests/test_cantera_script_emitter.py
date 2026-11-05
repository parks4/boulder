"""Tests for the downloadable script: the runner-based, stage-by-stage solve.

Covers ``boulder.download_script_emitter`` and ``DualCanteraConverter.script_load_lines``:
the class listing per stage, the check of importable classes, the stage objects
``runner.solve_stage`` returns, and the errors raised instead of a broken script.
"""

from __future__ import annotations

import ast
import copy
from typing import Any, Dict

import cantera as ct
import pytest

from boulder.cantera_converter import DualCanteraConverter
from boulder.config import normalize_config, validate_config
from boulder.download_script_emitter import (
    is_importable_class,
    qualified_class_name,
    script_lines_for_runner,
)
from boulder.runner import BoulderRunner
from boulder.staged_solver import build_stage_graph

_CONFIG: Dict[str, Any] = {
    "phases": {"gas": {"mechanism": "gri30.yaml"}},
    "network": [
        {
            "id": "r1",
            "IdealGasConstPressureMoleReactor": {
                "volume": 1.0e-5,
                "initial": {
                    "temperature": 1500,
                    "pressure": 101325,
                    "composition": "H2:1, O2:1",
                },
            },
        }
    ],
}


def _prepared() -> Dict[str, Any]:
    return validate_config(normalize_config(copy.deepcopy(_CONFIG)))


def _script(config: Dict[str, Any], node_classes: Dict[str, str]) -> str:
    plan = build_stage_graph(config)
    lines = script_lines_for_runner(
        "from boulder.runner import BoulderRunner",
        "BoulderRunner",
        config,
        plan,
        node_classes,
    )
    return "\n".join(lines)


def test_class_names_are_fully_qualified_and_importable() -> None:
    """``qualified_class_name`` gives ``module.QualName``; importable classes resolve."""
    name = qualified_class_name(ct.IdealGasReactor(ct.Solution("h2o2.yaml")))
    assert name == "cantera.reactor.IdealGasReactor"
    assert is_importable_class(name)
    assert not is_importable_class("no_such_module.Reactor")
    assert not is_importable_class("builtins.no_such_class")

    class Local(ct.Reactor):
        pass

    assert not is_importable_class(
        qualified_class_name(Local(ct.Solution("h2o2.yaml")))
    )


def test_script_is_valid_python_and_lists_each_stage_with_its_classes() -> None:
    """The script parses, has one solve_stage call, lists the node's class and checks it."""
    config = _prepared()
    text = _script(config, {"r1": "cantera.reactor.IdealGasConstPressureMoleReactor"})
    ast.parse(text)
    assert text.count("runner.solve_stage(") == 1
    assert "#     r1: cantera.reactor.IdealGasConstPressureMoleReactor\n" in text
    assert "'r1': 'cantera.reactor.IdealGasConstPressureMoleReactor'" in text
    assert "check_classes(stages['default'])" in text


def test_a_class_that_cannot_be_imported_is_listed_but_not_checked() -> None:
    """A node class with no importable name stays in the table, out of EXPECTED_CLASSES."""
    text = _script(_prepared(), {"r1": "__main__.Local"})
    assert "#     r1: __main__.Local\n" in text
    assert "EXPECTED_CLASSES = {}" in text


def test_a_continuation_section_is_run_through_run_continuation() -> None:
    """With a ``continuation:`` section the script calls ``runner.run_continuation()``."""
    config = _prepared()
    config["continuation"] = {
        "parameter": "nodes.r1.volume",
        "update": {"multiply": 0.5},
        "until": {"max_iters": 2},
    }
    text = _script(config, {})
    assert "runner.run_continuation()" in text
    assert "runner.solve_stage(" not in text


def test_a_config_that_is_not_a_literal_fails_loud() -> None:
    """A value that cannot be written as a literal raises instead of emitting a broken script."""
    config = _prepared()
    config["settings"] = {"bad": float("nan")}
    with pytest.raises(ValueError, match="cannot be written into a script"):
        _script(config, {})


def test_script_load_lines_requires_a_solved_config() -> None:
    """``script_load_lines`` before ``build_network`` raises ``RuntimeError``."""
    with pytest.raises(RuntimeError, match="build_network"):
        DualCanteraConverter().script_load_lines("x.yaml", None)


def test_solve_stage_returns_the_built_stage_objects() -> None:
    """``runner.solve_stage`` returns ``{node_id: reactor}`` of what the stage built."""
    runner = BoulderRunner(_prepared())
    plan = runner.build_stage_graph()
    built = runner.solve_stage(
        plan, plan.ordered_stages[0], {}, runner.new_trajectory()
    )
    assert isinstance(built["r1"], ct.IdealGasConstPressureMoleReactor)


def test_build_network_script_lists_the_classes_it_built() -> None:
    """The script a built converter writes names the class of each built node."""
    converter = DualCanteraConverter()
    converter.build_network(_prepared())
    text = "\n".join(converter.code_lines)
    assert "#     r1: cantera.reactor.IdealGasConstPressureMoleReactor\n" in text
    assert "runner.solve_stage(" in text


class _SubRunner(BoulderRunner):
    """A neutral host runner subclass."""


def test_script_imports_the_runner_class_that_solved_it() -> None:
    """The script imports and uses the runner subclass, on both converter routes.

    Asserts the converter made by ``BoulderRunner._ensure_converter`` (headless)
    and the one made by ``solve_scenario`` (GUI and sweep) write
    ``from <module> import _SubRunner`` and ``_SubRunner(config)``; with no
    runner set the script falls back to ``BoulderRunner``.
    """
    from boulder.sweep_runner import solve_scenario

    runner = _SubRunner(_prepared())
    runner.build()
    assert runner.converter is not None
    _, _, conv = solve_scenario(_prepared(), "gri30.yaml", runner_cls=_SubRunner)
    for converter in (runner.converter, conv):
        text = "\n".join(converter.code_lines)
        assert f"from {_SubRunner.__module__} import _SubRunner\n" in text
        assert "runner = _SubRunner(config)" in text
        assert "BoulderRunner" not in text
    plain = DualCanteraConverter()
    plain.build_network(_prepared())
    assert "runner = BoulderRunner(config)" in "\n".join(plain.code_lines)

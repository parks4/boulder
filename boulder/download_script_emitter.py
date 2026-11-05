"""Emit the downloadable script: the runner-based, stage-by-stage solve.

``--download`` and the GUI's "Download Python" write the same script.  It holds
the solved configuration, a table of the class each node runs (resolved when the
script is written, so a host's reactor subclasses show up by their own names) and
one ``runner.solve_stage`` call per stage -- the per-stage solve the pipeline
itself runs (:func:`boulder.staged_solver.solve_one_stage`).  Each call returns
the objects it built, kept in ``stages`` so a user can inspect or modify them
between stages, and the script checks them against the listed classes.
"""

from __future__ import annotations

import ast
import importlib
from pprint import pformat
from typing import Any, Dict, List, Optional

from .config import TRANSIENT_SOLVER_KINDS


def qualified_class_name(obj: Any) -> str:
    """Return the fully qualified class name of *obj*, as ``module.QualName``."""
    cls = type(obj)
    return f"{cls.__module__}.{cls.__qualname__}"


def is_importable_class(name: str) -> bool:
    """Whether *name* (``module.QualName``) resolves to a class by import."""
    module, _, qualname = name.rpartition(".")
    while module:
        try:
            target: Any = importlib.import_module(module)
        except ImportError:
            module, _, head = module.rpartition(".")
            qualname = f"{head}.{qualname}"
            continue
        for part in qualname.split("."):
            target = getattr(target, part, None)
        return isinstance(target, type)
    return False


#: Helper emitted into the script: fails loud when a built object is not of the
#: class the script lists for its node.
_CHECK_CLASSES = '''\
def check_classes(built):
    """Raise if a built object is not an instance of the class listed above."""
    for node_id, name in EXPECTED_CLASSES.items():
        if node_id not in built:
            continue
        module, _, qualname = name.rpartition(".")
        cls = importlib.import_module(module)
        for part in qualname.split("."):
            cls = getattr(cls, part)
        if not isinstance(built[node_id], cls):
            raise TypeError(f"{node_id}: expected {name}, built {type(built[node_id])}")
'''


def script_lines_for_runner(
    runner_import: str,
    runner_class: str,
    config: Dict[str, Any],
    plan: Any,
    node_classes: Optional[Dict[str, str]] = None,
) -> List[str]:
    """Emit the script's staged-solve part.

    Parameters
    ----------
    runner_import, runner_class :
        The import line and the name of the runner class the script uses.
    config :
        The configuration that was solved, before the solve added stream points.
        Embedded as a literal so the script solves what was solved (scenario
        overrides included), whatever file it came from.
    plan :
        The :class:`~boulder.staged_solver.StageExecutionPlan` of *config*.
    node_classes :
        ``{node_id: "module.Class"}`` as resolved at emission time from the
        built network.  Listed per stage; an importable class is also checked
        when the script runs.
    """
    literal = pformat(config, width=100, sort_dicts=False)
    try:
        ast.literal_eval(literal)
    except (ValueError, SyntaxError) as exc:
        raise ValueError(
            f"The solved configuration cannot be written into a script: {exc}"
        ) from exc

    node_classes = node_classes or {}
    stages = list(plan.ordered_stages)
    n = len(stages)

    table: List[str] = [
        "# Classes that run, per stage (as built when this script was written):"
    ]
    for i, stage in enumerate(stages):
        kind = (stage.solver or {}).get("kind", "advance_to_steady_state")
        table.append(f"#   Stage {i + 1}/{n} {stage.id}  [{stage.mechanism}, {kind}]")
        for node_id in stage.node_ids:
            table.append(f"#     {node_id}: {node_classes.get(node_id, '(not built)')}")
    expected = {
        node_id: name
        for node_id, name in node_classes.items()
        if is_importable_class(name)
    }

    lines = [
        runner_import,
        "import importlib",
        "",
        "# The configuration that was solved.",
        f"config = {literal}",
        "",
        *table,
        "EXPECTED_CLASSES = " + pformat(expected, width=100, sort_dicts=False),
        "",
        _CHECK_CLASSES,
        f"runner = {runner_class}(config)",
        "plan = runner.build_stage_graph()",
        "trajectory = runner.new_trajectory()",
        "inlet_states = {}",
        "# What each stage built, by stage id then node id: inspect or modify it",
        "# between stages (the next stage starts from `inlet_states`).",
        "stages = {}",
        "",
    ]

    if config.get("continuation"):
        lines += [
            "# The config's continuation section steps every stage once per parameter",
            "# value: one run_continuation call (the stage solve is the same).",
            "runner.run_continuation()",
            "trajectory = runner.converter._staged_trajectory",
            "",
        ]
    else:
        for i, stage in enumerate(stages):
            kind = (stage.solver or {}).get("kind", "advance_to_steady_state")
            done = "complete" if kind in TRANSIENT_SOLVER_KINDS else "converged"
            lines += [
                f"# Stage {i + 1}/{n}: {stage.id}  [nodes: {', '.join(stage.node_ids)}]",
                f"stages[{stage.id!r}] = runner.solve_stage(",
                f"    plan, plan.ordered_stages[{i}], inlet_states, trajectory",
                ")",
                f"check_classes(stages[{stage.id!r}])",
                f"print('Stage {stage.id} ({kind}) {done}.')",
                f"for _id, _r in stages[{stage.id!r}].items():",
                "    if hasattr(_r.phase, 'T'):",
                "        print(f'  {_id}: T={_r.phase.T:.1f} K  P={_r.phase.P:.0f} Pa')",
                "",
            ]
        lines += [
            "# Assemble visualization network from all converged states",
            "runner.build_viz_network(plan, trajectory)",
        ]
    lines += [
        "network = runner.network",
        "converter = runner.converter",
    ]
    return lines

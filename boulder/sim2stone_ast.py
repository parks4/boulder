"""AST-based pattern extraction from Cantera simulation Python scripts.

This module analyses the source code of a Cantera simulation script with Python
``ast`` to recognise:

1. ``ct.Func1("Gaussian", [...])`` and similar named constructors → ``Gaussian``
   signal block.
2. ``def mdot(t): return reactor.mass / tau`` + ``MassFlowController(..., mdot=...)``
   → ``closure: residence_time`` on the connection, no top-level signal block.
3. ``while reactor.T > N: sim.solve_steady(); tau *= k`` → ``continuation:`` block.
4. ``while t < t_total: sim.advance(...)`` → ``advance_grid`` / ``micro_step`` solver.

All detections carry ``derived_via`` metadata to annotate emitted YAML.

This module is deliberately side-effect free: it only reads source text and
returns description objects; it does not modify any Cantera state.
"""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Result datatypes
# ---------------------------------------------------------------------------


@dataclass
class DetectedSignal:
    """A ``signals:`` block entry derived from an AST pattern.

    Attributes
    ----------
    signal_id:
        Unique identifier to emit in the YAML ``signals:`` list.
    kind:
        STONE signal kind, e.g. ``Gaussian``, ``Sine``, ``Constant``,
        ``PiecewiseLinear``.
    params:
        Key-value parameters for the block (e.g. ``peak``, ``center``, ``fwhm``
        for Gaussian).
    source_var:
        Original Python variable name that held the ``ct.Func1`` object.
    derived_via:
        One of ``ast_match``, ``func1_introspection``, ``trace_reconstruction``,
        ``snapshot``.
    """

    signal_id: str
    kind: str
    params: Dict[str, Any]
    source_var: str = ""
    derived_via: str = "ast_match"


@dataclass
class DetectedBinding:
    """A ``bindings:`` block entry derived from an AST pattern."""

    signal_id: str
    target: str
    derived_via: str = "ast_match"


@dataclass
class DetectedClosure:
    """Detected residence-time closure on a MassFlowController.

    When a ``def mdot(t): return reactor.mass / tau`` + ``MFC(..., mdot=mdot)``
    pattern is found the connection should use ``closure: residence_time``
    instead of a top-level signal.
    """

    mfc_var: str
    reactor_var: str
    tau_var: str
    derived_via: str = "ast_match"


@dataclass
class DetectedContinuation:
    """Detected ``while reactor.T > N: sim.solve_steady(); tau *= k`` pattern."""

    tau_var: str
    tau_factor: float
    condition_attr: str
    condition_threshold: float
    derived_via: str = "ast_match"


@dataclass
class DetectedSolver:
    """Solver kind derived from the simulation loop structure."""

    kind: str
    params: Dict[str, Any] = field(default_factory=dict)
    derived_via: str = "ast_match"


@dataclass
class ASTExtractionResult:
    """Aggregated result of scanning a Python source file."""

    signals: List[DetectedSignal] = field(default_factory=list)
    bindings: List[DetectedBinding] = field(default_factory=list)
    closures: List[DetectedClosure] = field(default_factory=list)
    continuations: List[DetectedContinuation] = field(default_factory=list)
    solver: Optional[DetectedSolver] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _eval_const(node: ast.expr) -> Optional[Any]:
    """Evaluate a constant or simple arithmetic AST node to a Python value.

    Supports: literals (int, float, str), unary minus, binary ops ``*`` / ``/``,
    attribute access ``ct.one_atm``, and ``Name`` references to common constants.
    """
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        inner = _eval_const(node.operand)
        if inner is not None:
            return -inner
    if isinstance(node, ast.BinOp):
        left = _eval_const(node.left)
        right = _eval_const(node.right)
        if left is not None and right is not None:
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
    if isinstance(node, ast.Attribute):
        if isinstance(node.value, ast.Name) and node.value.id in ("ct", "cantera"):
            if node.attr == "one_atm":
                return 101325.0
    return None


def _is_ct_func1_call(node: ast.expr) -> bool:
    """Return True if *node* is a ``ct.Func1(...)`` call."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "Func1"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in ("ct", "cantera")
    )


def _list_to_floats(node: ast.expr) -> Optional[List[float]]:
    """Try to convert a list-literal AST node to a Python list of floats."""
    if not isinstance(node, ast.List):
        return None
    result: List[float] = []
    for elt in node.elts:
        v = _eval_const(elt)
        if v is None or not isinstance(v, (int, float)):
            return None
        result.append(float(v))
    return result


# ---------------------------------------------------------------------------
# Func1 introspection helper (runtime, not AST)
# ---------------------------------------------------------------------------


def introspect_func1(func1_obj: Any) -> Optional[DetectedSignal]:
    """Try to extract a ``DetectedSignal`` from a live ``ct.Func1`` object.

    Uses the Cantera ``Func1.type`` attribute to identify the kind, then maps
    the type to known parameter conventions.

    Returns ``None`` when the type is unknown or introspection fails.
    """
    try:
        ftype = str(func1_obj.type)
    except Exception:
        return None

    kind_map = {
        "Gaussian": "Gaussian",
        "constant": "Constant",
        "sin": "Sine",
        "tabulated-linear": "PiecewiseLinear",
        "tabulated": "PiecewiseLinear",
    }
    mapped = kind_map.get(ftype)
    if mapped is None:
        return None

    params: Dict[str, Any] = {"_note": f"introspected from ct.Func1.type={ftype!r}"}

    if mapped == "Constant":
        try:
            params = {"value": float(func1_obj(0.0))}
        except Exception:
            pass

    elif mapped == "Gaussian":
        # We cannot extract the coefficients from a live ct.Func1 Gaussian
        # reliably; record what we know and annotate.
        try:
            peak_guess = float(func1_obj(0.0))
            params = {
                "_note": (
                    "Gaussian parameters not extractable from live object; "
                    "see source for peak/center/fwhm"
                )
            }
        except Exception:
            pass

    elif mapped == "Sine":
        try:
            write = str(func1_obj.write())
            params = {"_note": f"Sine, write()={write!r}"}
        except Exception:
            pass

    return DetectedSignal(
        signal_id="",
        kind=mapped,
        params=params,
        derived_via="func1_introspection",
    )


# ---------------------------------------------------------------------------
# Main AST scanner
# ---------------------------------------------------------------------------


def _collect_scalar_assignments(tree: ast.AST) -> Dict[str, float]:
    """Collect all module-level ``name = <scalar_expr>`` assignments.

    Evaluates simple arithmetic expressions (constants, ``*``, ``/``,
    ``**``, attribute accesses like ``ct.one_atm``, ``np.log``).
    Used to resolve variable names inside ``ct.Func1([...])`` arg lists.
    """
    scalars: Dict[str, float] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        v = _eval_const_extended(node.value, scalars)
        if isinstance(v, (int, float)):
            scalars[node.targets[0].id] = float(v)
    return scalars


def _eval_const_extended(node: ast.expr, env: Dict[str, float]) -> Optional[Any]:
    """Extended constant evaluator that resolves names from *env*."""
    if isinstance(node, ast.Name) and node.id in env:
        return env[node.id]
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        inner = _eval_const_extended(node.operand, env)
        if inner is not None:
            return -inner
    if isinstance(node, ast.BinOp):
        left = _eval_const_extended(node.left, env)
        right = _eval_const_extended(node.right, env)
        if left is not None and right is not None:
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
            if isinstance(node.op, ast.Pow):
                return left**right
    if isinstance(node, ast.Attribute):
        if isinstance(node.value, ast.Name) and node.value.id in ("ct", "cantera"):
            if node.attr == "one_atm":
                return 101325.0
        # np.log(2), np.pi, etc.
        if isinstance(node.value, ast.Name) and node.value.id in (
            "np",
            "numpy",
            "math",
        ):
            import math as _math

            attr = getattr(_math, node.attr, None)
            if isinstance(attr, float):
                return attr
    if isinstance(node, ast.Call):
        # np.log(x), math.sqrt(x), etc.
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id in ("np", "numpy", "math")
        ):
            import math as _math

            fn = getattr(_math, func.attr, None)
            if callable(fn) and len(node.args) == 1:
                arg = _eval_const_extended(node.args[0], env)
                if isinstance(arg, (int, float)):
                    try:
                        return fn(arg)
                    except Exception:
                        pass
    return None


def _list_to_floats_extended(
    node: ast.expr, env: Dict[str, float]
) -> Optional[List[float]]:
    """Try to convert a list-literal AST node to a Python list of floats, resolving names."""
    if not isinstance(node, ast.List):
        return None
    result: List[float] = []
    for elt in node.elts:
        v = _eval_const_extended(elt, env)
        if v is None or not isinstance(v, (int, float)):
            return None
        result.append(float(v))
    return result


class _Func1CallVisitor(ast.NodeVisitor):
    """Walk the AST and record ``ct.Func1(kind, [...])`` assignments."""

    def __init__(self, scalar_env: Optional[Dict[str, float]] = None) -> None:
        self.assignments: List[Tuple[str, str, List[float]]] = []
        self._env: Dict[str, float] = scalar_env or {}
        # var_name, func1_kind, args_list

    def visit_Assign(self, node: ast.Assign) -> None:
        if not (
            len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and _is_ct_func1_call(node.value)
        ):
            self.generic_visit(node)
            return

        var_name = node.targets[0].id
        call: ast.Call = node.value  # type: ignore[assignment]
        if not call.args:
            self.generic_visit(node)
            return

        kind_arg = call.args[0]
        if not isinstance(kind_arg, ast.Constant) or not isinstance(
            kind_arg.value, str
        ):
            self.generic_visit(node)
            return
        kind = kind_arg.value

        if len(call.args) < 2:
            self.assignments.append((var_name, kind, []))
            self.generic_visit(node)
            return

        args_node = call.args[1]
        # Try extended resolution first (resolves variable names from env)
        args_list = _list_to_floats_extended(args_node, self._env)
        if args_list is None:
            # Fall back to pure-constant evaluation
            args_list = _list_to_floats(args_node) or []

        self.assignments.append((var_name, kind, args_list))
        self.generic_visit(node)


def _detect_func1_signals(tree: ast.AST) -> List[DetectedSignal]:
    """Scan *tree* for ``ct.Func1(kind, [...])`` assignments."""
    scalar_env = _collect_scalar_assignments(tree)
    visitor = _Func1CallVisitor(scalar_env=scalar_env)
    visitor.visit(tree)

    # Maps ct.Func1 kind string → (STONE signal kind, param factory)
    _kind_to_stone: Dict[str, Tuple[str, Any]] = {
        "Gaussian": ("Gaussian", _params_gaussian),
        "sin": ("Sine", _params_sine),
        "constant": ("Constant", _params_constant),
        "tabulated-linear": ("PiecewiseLinear", _params_piecewise),
        "tabulated": ("PiecewiseLinear", _params_piecewise),
    }

    results: List[DetectedSignal] = []
    for var_name, kind, args in visitor.assignments:
        entry = _kind_to_stone.get(kind)
        if entry is None:
            continue
        stone_kind, mapper = entry
        params = mapper(args)
        results.append(
            DetectedSignal(
                signal_id=var_name,
                kind=stone_kind,
                params=params,
                source_var=var_name,
                derived_via="ast_match",
            )
        )
    return results


def _params_gaussian(args: List[float]) -> Dict[str, Any]:
    if len(args) >= 3:
        return {"peak": args[0], "center": args[1], "fwhm": args[2]}
    return {}


def _params_sine(args: List[float]) -> Dict[str, Any]:
    if len(args) >= 1:
        return {"amplitude": 1.0, "frequency": args[0], "phase": 0.0, "offset": 0.0}
    return {}


def _params_constant(args: List[float]) -> Dict[str, Any]:
    if len(args) >= 1:
        return {"value": args[0]}
    return {}


def _params_piecewise(args: List[float]) -> Dict[str, Any]:
    return {}


# ---------------------------------------------------------------------------
# Closure detection
# ---------------------------------------------------------------------------


def _detect_residence_time_closures(
    tree: ast.AST,
) -> List[DetectedClosure]:
    """Detect ``def mdot(t): return reactor.mass / tau_var`` patterns.

    Also looks for ``MassFlowController(..., mdot=<var>)`` to link the function
    to the MFC variable.
    """
    closures: List[DetectedClosure] = []

    # Step 1: collect simple ``def name(t): return reactor_var.mass / tau_var``
    closure_funcs: Dict[str, Tuple[str, str]] = {}
    # func_name -> (reactor_var, tau_var)

    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        func = node
        if len(func.args.args) != 1:
            continue
        if len(func.body) != 1 or not isinstance(func.body[0], ast.Return):
            continue
        ret: ast.Return = func.body[0]
        if ret.value is None:
            continue
        # Match: return X.mass / tau_var
        val = ret.value
        if not (isinstance(val, ast.BinOp) and isinstance(val.op, ast.Div)):
            continue
        left = val.left
        right = val.right
        if not (
            isinstance(left, ast.Attribute)
            and left.attr == "mass"
            and isinstance(left.value, ast.Name)
            and isinstance(right, ast.Name)
        ):
            continue
        reactor_var = left.value.id
        tau_var = right.id
        closure_funcs[func.name] = (reactor_var, tau_var)

    # Step 2: find ``MassFlowController(..., mdot=<func_name>)`` calls
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        assign: ast.Assign = node
        if not (len(assign.targets) == 1 and isinstance(assign.targets[0], ast.Name)):
            continue
        mfc_var = assign.targets[0].id
        call = assign.value
        if not isinstance(call, ast.Call):
            continue
        # Check for MassFlowController
        callee = call.func
        is_mfc = (
            isinstance(callee, ast.Attribute) and callee.attr == "MassFlowController"
        ) or (isinstance(callee, ast.Name) and callee.id == "MassFlowController")
        if not is_mfc:
            continue
        mdot_kw = next(
            (kw for kw in call.keywords if kw.arg == "mdot"),
            None,
        )
        if mdot_kw is None:
            continue
        func_name = mdot_kw.value.id if isinstance(mdot_kw.value, ast.Name) else None
        if func_name is None or func_name not in closure_funcs:
            continue
        reactor_var, tau_var = closure_funcs[func_name]
        closures.append(
            DetectedClosure(
                mfc_var=mfc_var,
                reactor_var=reactor_var,
                tau_var=tau_var,
                derived_via="ast_match",
            )
        )
    return closures


# ---------------------------------------------------------------------------
# Continuation detection
# ---------------------------------------------------------------------------


def _detect_continuation(tree: ast.AST) -> Optional[DetectedContinuation]:
    """Detect ``while reactor.T > N: sim.solve_steady(); tau *= k`` loop."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.While):
            continue
        loop: ast.While = node

        # Check condition: ``reactor_var.attr > number``
        test = loop.test
        if not isinstance(test, ast.Compare):
            continue
        if len(test.ops) != 1 or not isinstance(test.ops[0], ast.Gt):
            continue
        left = test.left
        if not isinstance(left, ast.Attribute):
            continue
        cond_attr = left.attr
        thresh = _eval_const(test.comparators[0])
        if thresh is None or not isinstance(thresh, (int, float)):
            continue

        # Look for ``tau *= k`` in the loop body
        tau_var: Optional[str] = None
        tau_factor: Optional[float] = None
        for stmt in ast.walk(loop):
            if not isinstance(stmt, ast.AugAssign):
                continue
            if not isinstance(stmt.op, ast.Mult):
                continue
            if not isinstance(stmt.target, ast.Name):
                continue
            factor = _eval_const(stmt.value)
            if isinstance(factor, (int, float)):
                tau_var = stmt.target.id
                tau_factor = float(factor)
                break

        # Look for ``sim.solve_steady()`` in body
        has_solve_steady = any(
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Call)
            and isinstance(stmt.value.func, ast.Attribute)
            and stmt.value.func.attr == "solve_steady"
            for stmt in ast.walk(loop)
        )

        if not has_solve_steady:
            continue

        if tau_var is None or tau_factor is None:
            # There is a solve_steady loop, emit without continuation params
            return DetectedContinuation(
                tau_var="",
                tau_factor=0.0,
                condition_attr=cond_attr,
                condition_threshold=float(thresh),
                derived_via="ast_match",
            )

        return DetectedContinuation(
            tau_var=tau_var,
            tau_factor=float(tau_factor),
            condition_attr=cond_attr,
            condition_threshold=float(thresh),
            derived_via="ast_match",
        )
    return None


# ---------------------------------------------------------------------------
# Solver loop detection
# ---------------------------------------------------------------------------


def _detect_solver_hint(tree: ast.AST) -> Optional[DetectedSolver]:
    """Derive solver hint from the main simulation loop.

    Patterns:
    - ``while t < t_total: ... sim.advance(sim.time + dt) ...``
      → ``advance_grid`` or ``micro_step``
    - ``for n in range(n_steps): ... sim.advance(time) ...``
      → ``advance_grid``
    - ``sim.advance_to_steady_state()`` or ``sim.solve_steady()`` at top level
      → ``solve_steady`` (but solve_steady in a while loop → handled by
      continuation detection)
    """
    # Walk over all While loops to find transient advance loops
    for node in ast.walk(tree):
        if not isinstance(node, ast.While):
            continue
        # Check for sim.advance call (not solve_steady)
        has_advance = any(
            isinstance(s, ast.Expr)
            and isinstance(s.value, ast.Call)
            and isinstance(s.value.func, ast.Attribute)
            and s.value.func.attr == "advance"
            for s in ast.walk(node)
        )
        has_reinitialize = any(
            isinstance(s, ast.Expr)
            and isinstance(s.value, ast.Call)
            and isinstance(s.value.func, ast.Attribute)
            and s.value.func.attr == "reinitialize"
            for s in ast.walk(node)
        )
        if has_advance:
            # Micro-step if there is also a reinitialize (chunk-boundary update)
            kind = "micro_step" if has_reinitialize else "advance_grid"
            extra: Dict[str, Any] = {}
            if has_reinitialize:
                extra["reinitialize_between_chunks"] = True
            return DetectedSolver(kind=kind, params=extra, derived_via="ast_match")

    # Walk over For loops (for n in range(n_steps))
    for node in ast.walk(tree):
        if not isinstance(node, ast.For):
            continue
        has_advance = any(
            isinstance(s, ast.Expr)
            and isinstance(s.value, ast.Call)
            and isinstance(s.value.func, ast.Attribute)
            and s.value.func.attr == "advance"
            for s in ast.walk(node)
        )
        if has_advance:
            return DetectedSolver(
                kind="advance_grid", params={}, derived_via="ast_match"
            )

    # Top-level advance_to_steady_state
    for node in ast.walk(tree):
        if not isinstance(node, ast.Expr):
            continue
        call = node.value
        if (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "advance_to_steady_state"
        ):
            return DetectedSolver(
                kind="advance_to_steady_state", params={}, derived_via="ast_match"
            )

    return None


def _detect_advance_timing(tree: ast.AST) -> Dict[str, Any]:
    """Extract timing scalars from module-level assignments and for-loop increments.

    Looks for:
    - Named assignments: ``t_total``, ``dt_max``, ``dt_chunk``, ``n_steps``, ``dt``
    - AugAssign increments inside For loops: ``time += 4e-4`` → ``step_size``
    """
    timing: Dict[str, Any] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        vname = node.targets[0].id
        if vname in ("t_total", "dt_max", "dt_chunk", "n_steps", "step_size", "dt"):
            v = _eval_const(node.value)
            if v is not None:
                timing[vname] = v

    # Detect ``time += dt_value`` inside For loops
    for node in ast.walk(tree):
        if not isinstance(node, ast.For):
            continue
        for stmt in ast.walk(node):
            if not isinstance(stmt, ast.AugAssign):
                continue
            if not isinstance(stmt.op, ast.Add):
                continue
            v = _eval_const(stmt.value)
            if isinstance(v, (int, float)):
                timing.setdefault("step_size", float(v))
                break

    return timing


# ---------------------------------------------------------------------------
# Binding derivation
# ---------------------------------------------------------------------------


def _derive_bindings(
    signals: List[DetectedSignal],
    tree: ast.AST,
) -> List[DetectedBinding]:
    """Find where Func1 signals are used to drive plasma / MFC targets.

    Currently detects:
    - ``gas.reduced_electric_field = var(t)`` or ``gas.reduced_electric_field = var``
      → ``nodes.<reactor_id>.reduced_electric_field``
    - MFC ``mass_flow_rate`` from a Func1 variable (not closure; those are handled
      separately in DetectedClosure)
    """
    sig_ids = {s.source_var for s in signals}
    bindings: List[DetectedBinding] = []

    # Detect reduced_electric_field assignments
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        target = node.targets[0] if node.targets else None
        if not (
            isinstance(target, ast.Attribute)
            and target.attr == "reduced_electric_field"
        ):
            continue
        # The value might be ``var(t)`` or bare ``var``
        val = node.value
        called_var: Optional[str] = None
        if isinstance(val, ast.Call) and isinstance(val.func, ast.Name):
            called_var = val.func.id
        elif isinstance(val, ast.Name):
            called_var = val.id
        if called_var in sig_ids:
            bindings.append(
                DetectedBinding(
                    signal_id=called_var,
                    # We don't know the node id from AST alone; use placeholder
                    target="nodes.<reactor>.reduced_electric_field",
                    derived_via="ast_match",
                )
            )
    return bindings


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_from_source(source_file: str) -> ASTExtractionResult:
    """Parse a Python source file and return all detected patterns.

    Does not execute any code.  Returns an ``ASTExtractionResult`` with all
    found signals, closures, continuations, and solver hints.

    Gracefully returns an empty result if the file cannot be parsed.
    """
    result = ASTExtractionResult()
    if not os.path.isfile(source_file):
        return result

    try:
        source = open(source_file, encoding="utf-8").read()
        tree = ast.parse(source)
    except Exception:
        return result

    result.signals = _detect_func1_signals(tree)
    result.closures = _detect_residence_time_closures(tree)
    result.continuations = _cont_list(_detect_continuation(tree))
    solver = _detect_solver_hint(tree)
    if solver is not None:
        timing = _detect_advance_timing(tree)
        if timing:
            solver.params.update(timing)
        result.solver = solver

    result.bindings = _derive_bindings(result.signals, tree)
    return result


def _cont_list(c: Optional[DetectedContinuation]) -> List[DetectedContinuation]:
    return [c] if c is not None else []

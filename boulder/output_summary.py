"""Simple output summary for STONE configs.

Supports two formats:
1. Mapping: output: {reactor_id: "temperature", reactor_id2: ["temperature, K", "pressure, bar"]}
2. List: output: [{reactor_id: "temperature"}, {reactor_id2: "pressure, bar"}]

Units are parsed from strings like "temperature, K" or "pressure, bar".
Formulas like "R1.T() + R2.P()" are evaluated using final simulation values.
"""

import ast
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from pint import UnitRegistry


@dataclass
class OutputItem:
    reactor: str
    quantity: str  # "temperature", "pressure", or "formula"
    unit: Optional[str] = None
    expression: Optional[str] = None


def parse_output_block(output_block: Any) -> List[OutputItem]:
    """Parse output block into list of OutputItem."""
    if not output_block:
        return []

    items = []

    if isinstance(output_block, dict):
        # Format: {reactor_id: spec}
        for reactor_id, spec in output_block.items():
            items.extend(_parse_reactor_spec(str(reactor_id), spec))

    elif isinstance(output_block, list):
        # Format: [{reactor_id: spec}, ...]
        for entry in output_block:
            if not isinstance(entry, dict):
                raise ValueError(
                    "List entries must be dicts like {reactor_id: 'temperature'}"
                )
            for reactor_id, spec in entry.items():
                items.extend(_parse_reactor_spec(str(reactor_id), spec))

    else:
        raise ValueError("Output block must be dict or list")

    return items


def _parse_reactor_spec(reactor_id: str, spec: Any) -> List[OutputItem]:
    """Parse a single reactor's output specification."""
    if isinstance(spec, str):
        return [_parse_spec_string(reactor_id, spec)]

    elif isinstance(spec, list):
        return [_parse_spec_string(reactor_id, s) for s in spec if isinstance(s, str)]

    else:
        raise ValueError(f"Spec for {reactor_id} must be string or list of strings")


def _parse_spec_string(reactor_id: str, spec: str) -> OutputItem:
    """Parse a spec string like 'temperature, K' or 'R1.T() + R2.P()'."""
    # Check if it's a simple quantity with optional unit
    parts = [p.strip() for p in spec.split(",", 1)]
    quantity_token = parts[0].lower()
    unit = parts[1] if len(parts) > 1 else None

    if quantity_token in {"temperature", "temp", "t"}:
        return OutputItem(reactor=reactor_id, quantity="temperature", unit=unit)
    elif quantity_token in {"pressure", "press", "p"}:
        return OutputItem(reactor=reactor_id, quantity="pressure", unit=unit)
    else:
        # Treat as formula expression
        return OutputItem(reactor=reactor_id, quantity="formula", expression=spec)


def evaluate_output_items(
    items: List[OutputItem], results: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Evaluate output items against simulation results."""
    evaluated = []
    reactors = results.get("reactors", {})

    for item in items:
        entry = {
            "reactor": item.reactor,
            "quantity": item.quantity,
            "unit": item.unit,
            "expression": item.expression,
            "value": None,
        }

        try:
            if item.quantity == "temperature":
                final_k = reactors[item.reactor]["T"][-1]
                entry["value"] = _convert_temperature(final_k, item.unit)

            elif item.quantity == "pressure":
                final_pa = reactors[item.reactor]["P"][-1]
                entry["value"] = _convert_pressure(final_pa, item.unit)

            elif item.quantity == "formula":
                entry["value"] = _evaluate_formula(item.expression, results)

        except Exception as e:
            entry["error"] = str(e)

        evaluated.append(entry)

    return evaluated


def _convert_temperature(kelvin: float, unit: Optional[str]) -> float:
    """Convert temperature from Kelvin."""
    if not unit or unit.lower() in {"k", "kelvin"}:
        return kelvin
    elif unit.lower() in {"c", "degc", "celsius"}:
        return kelvin - 273.15
    elif unit.lower() in {"f", "degf", "fahrenheit"}:
        return (kelvin - 273.15) * 9 / 5 + 32
    else:
        raise ValueError(f"Unknown temperature unit: {unit}")


def _convert_pressure(pascal: float, unit: Optional[str]) -> float:
    """Convert pressure from Pascal."""
    if not unit or unit.lower() == "pa":
        return pascal

    ureg = UnitRegistry()
    try:
        return ureg.Quantity(pascal, "Pa").to(unit).magnitude
    except Exception:
        raise ValueError(f"Unknown pressure unit: {unit}")


def _evaluate_formula(expression: str, results: Dict[str, Any]) -> float:
    """Evaluate formula like 'R1.T() + R2.P()' using simulation results."""
    if not expression:
        raise ValueError("Empty formula")

    # Simple DSL: reactor.T(unit?) and reactor.P(unit?) and reactor.X(species)
    def repl_func(match):
        reactor = match.group(1)
        func = match.group(2).upper()
        arg = match.group(3) if match.group(3) else '""'
        if not arg.startswith('"'):
            arg = f'"{arg}"'
        return f'{func}("{reactor}", {arg})'

    # Convert R1.T(K) -> T("R1", "K")
    rewritten = re.sub(r"(\w+)\.(T|P|X)\(([^)]*)\)", repl_func, expression)

    # Parse and validate AST
    try:
        tree = ast.parse(rewritten, mode="eval")
    except SyntaxError as e:
        raise ValueError(f"Invalid formula syntax: {e}")

    # Simple validation - only allow basic operations and our functions
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if not (
                isinstance(node.func, ast.Name) and node.func.id in {"T", "P", "X"}
            ):
                raise ValueError(
                    f"Function not allowed: {node.func.id if hasattr(node.func, 'id') else 'unknown'}"
                )

    # Define safe functions
    def T(reactor_id: str, unit: str = "") -> float:
        final_k = results["reactors"][reactor_id]["T"][-1]
        return _convert_temperature(final_k, unit if unit else None)

    def P(reactor_id: str, unit: str = "") -> float:
        final_pa = results["reactors"][reactor_id]["P"][-1]
        return _convert_pressure(final_pa, unit if unit else None)

    def X(reactor_id: str, species: str) -> float:
        return results["reactors"][reactor_id]["X"][species][-1]

    namespace = {"T": T, "P": P, "X": X, "__builtins__": {}}

    return float(eval(compile(tree, "<formula>", "eval"), namespace))


def format_summary_text(evaluated_items: List[Dict[str, Any]]) -> str:
    """Format evaluated items as readable text."""
    if not evaluated_items:
        return "No output summary configured."

    lines = ["SIMULATION SUMMARY", "=" * 50, ""]

    for item in evaluated_items:
        reactor = item["reactor"]
        quantity = item["quantity"]
        value = item.get("value")
        unit = item.get("unit", "")
        error = item.get("error")

        if error:
            lines.append(f"{reactor} {quantity}: ERROR - {error}")
        elif value is not None:
            if unit:
                lines.append(f"{reactor} {quantity}: {value:.3f} {unit}")
            else:
                lines.append(f"{reactor} {quantity}: {value:.3f}")
        else:
            lines.append(f"{reactor} {quantity}: (no value)")

    return "\n".join(lines)

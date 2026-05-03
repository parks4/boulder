"""Unit-map helpers for YAML live sync.

Builds a map of unit-bearing scalar paths from a ruamel CommentedMap tree so
that SI float values in the updated config can be converted back to the
original unit strings (e.g. ``1 atm``, ``10 kg/h``, ``500 degC``) when the
YAML editor is synced with the live GUI state.

Key types
---------
UnitEntry : tuple
    ``(original_text: str, orig_unit_str: str, si_value: float,
       scalar_cls: type)``

    * ``original_text``  – verbatim text as it appeared in the YAML, e.g.
      ``"1 atm"`` or ``"298.15 K"``.
    * ``orig_unit_str``  – unit token extracted from the text, e.g. ``"atm"``.
    * ``si_value``       – canonical SI float the original text converts to.
    * ``scalar_cls``     – the ruamel scalar subclass (or ``str``) that should
      be used when emitting a replacement so quoting style is preserved.

UnitMap : dict
    ``{(item_id_or_none, key_path_tuple): UnitEntry}``

    *item_id_or_none* is the value of the ``id`` key inside the nearest
    enclosing network/stage list item, or ``None`` for top-level scalars.
    *key_path_tuple* is a tuple of string keys leading from the item root
    (or from the document root for top-level scalars) to the scalar.

    Using ``id`` instead of list indices makes the map stable when the list
    is reordered or filtered (e.g. synthesized satellites removed).
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from .utils import _UNIT_STRING_RE, _get_pint_ureg

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

# (orig_text, orig_unit_str, si_value, scalar_cls)
UnitEntry = Tuple[str, str, float, type]
# {(item_id_or_none, key_path_tuple) -> UnitEntry}
UnitMap = Dict[Tuple[Optional[str], tuple], UnitEntry]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _scalar_cls(val: Any) -> type:
    """Return the ruamel scalar subclass (or str) for *val*."""
    try:
        from ruamel.yaml.scalarstring import (  # noqa: PLC0415
            DoubleQuotedScalarString,
            PlainScalarString,
            SingleQuotedScalarString,
        )

        for cls in (SingleQuotedScalarString, DoubleQuotedScalarString, PlainScalarString):
            if isinstance(val, cls):
                return cls
    except ImportError:
        pass
    return str


def _parse_unit_entry(text: str, property_name: str) -> Optional[UnitEntry]:
    """Parse *text* as ``"<number> <unit>"`` and return a :data:`UnitEntry`.

    Returns ``None`` if *text* does not match the unit-string pattern or if
    Pint cannot parse the unit.
    """
    if not isinstance(text, str):
        return None
    m = _UNIT_STRING_RE.match(text)
    if not m:
        return None
    num_str, unit_str = m.group(1), m.group(2)
    from .utils import _PROPERTY_UNIT_HINTS  # noqa: PLC0415

    target_unit = _PROPERTY_UNIT_HINTS.get(property_name)
    try:
        ureg = _get_pint_ureg()
        qty = ureg.Quantity(float(num_str), unit_str)
        if target_unit is not None:
            si_val = float(qty.to(target_unit).magnitude)
        else:
            si_val = float(qty.to_base_units().magnitude)
        return (text, unit_str, si_val, _scalar_cls(text))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# build_unit_map
# ---------------------------------------------------------------------------

def build_unit_map(ruamel_tree: Any) -> UnitMap:
    """Walk a ruamel YAML tree and record every unit-bearing scalar.

    Parameters
    ----------
    ruamel_tree:
        A ``CommentedMap`` (or plain ``dict``) returned by
        ``load_yaml_string_with_comments``.

    Returns
    -------
    UnitMap
        Dict keyed by ``(item_id_or_none, key_path_tuple)``.
    """
    result: UnitMap = {}

    def _walk_item(node: Any, item_id: Optional[str], path: tuple) -> None:
        """Recurse into *node* collecting unit entries."""
        if isinstance(node, dict):
            for k, v in node.items():
                child_path = path + (k,)
                entry = _parse_unit_entry(v, property_name=k)
                if entry is not None:
                    result[(item_id, child_path)] = entry
                else:
                    _walk_item(v, item_id, child_path)
        elif isinstance(node, list):
            for item in node:
                if isinstance(item, dict) and "id" in item:
                    # Network/stage list item — use its id as key prefix.
                    _walk_item(item, item["id"], ())
                else:
                    _walk_item(item, item_id, path)
        # Scalars without a unit match are ignored.

    if not isinstance(ruamel_tree, dict):
        return result

    # Walk top-level network or stages lists, plus top-level scalar keys.
    for top_key, top_val in ruamel_tree.items():
        if isinstance(top_val, list):
            # Could be network: or a stage list.
            _walk_item(top_val, None, (top_key,))
        elif isinstance(top_val, dict):
            _walk_item(top_val, None, (top_key,))
        else:
            entry = _parse_unit_entry(top_val, property_name=top_key)
            if entry is not None:
                result[(None, (top_key,))] = entry

    return result


# ---------------------------------------------------------------------------
# apply_unit_map_inplace
# ---------------------------------------------------------------------------

def apply_unit_map_inplace(
    merged_tree: Any,
    unit_map: UnitMap,
    updated_config: Dict[str, Any],
) -> List[str]:
    """Replace SI float scalars in *merged_tree* with original unit strings.

    Walks the merged ruamel tree **in place**.  For each leaf scalar that has
    an entry in *unit_map*:

    * If the corresponding SI value in *updated_config* equals the original SI
      value (within ``rel_tol=1e-9``): the original verbatim text is restored
      (style-preserving, no change if ruamel already emitted it correctly).
    * If the value differs: a new string of the form
      ``"<new_magnitude_in_orig_unit:g> <orig_unit>"`` is written, using the
      same ruamel scalar subclass as the original for quoting style.

    Parameters
    ----------
    merged_tree:
        Ruamel ``CommentedMap`` as returned by the merge step.
    updated_config:
        Internal (normalized, SI) config dict from the frontend.  Used only to
        look up the current SI value for each property.
    unit_map:
        Built by :func:`build_unit_map` from the ``original_yaml`` string.

    Returns
    -------
    List[str]
        Warning strings for any paths where Pint inverse conversion failed.
        An empty list means full success.
    """
    warnings: List[str] = []

    # Build a fast lookup: item_id -> internal node/connection properties.
    node_props: Dict[str, Dict[str, Any]] = {}
    for n in updated_config.get("nodes", []):
        node_props[n["id"]] = n.get("properties") or {}
    conn_props: Dict[str, Dict[str, Any]] = {}
    for c in updated_config.get("connections", []):
        conn_props[c["id"]] = c.get("properties") or {}

    def _get_si_value(item_id: Optional[str], key_path: tuple) -> Optional[float]:
        """Look up the current SI float for *key_path* under *item_id*."""
        if item_id is None:
            # Top-level scalar (e.g. inside metadata).
            node = merged_tree
            for k in key_path:
                if not isinstance(node, dict) or k not in node:
                    return None
                node = node[k]
            return node if isinstance(node, (int, float)) else None

        # Item inside a network list.  The key_path is relative to the item
        # root.  STONE format: first key is the component-type key, rest is
        # the property name.
        if item_id in node_props:
            props = node_props[item_id]
        elif item_id in conn_props:
            props = conn_props[item_id]
        else:
            return None

        # Flatten key_path: skip the component-type key (index 0) and dig in.
        if len(key_path) >= 2:
            # path[0] is the STONE kind key (e.g. "Reservoir") – skip it.
            prop_key = key_path[-1]
        elif len(key_path) == 1:
            prop_key = key_path[0]
        else:
            return None

        val = props.get(prop_key)
        return val if isinstance(val, (int, float)) else None

    def _make_replacement(orig_text: str, orig_unit_str: str, new_si_val: float,
                          scalar_cls: type, path_label: str) -> Optional[str]:
        """Convert *new_si_val* back to *orig_unit_str* and format as string."""
        from .utils import _PROPERTY_UNIT_HINTS  # noqa: PLC0415

        # Infer the property name from the last segment of the path.
        prop_name = path_label.split(".")[-1] if path_label else ""
        target_unit = _PROPERTY_UNIT_HINTS.get(prop_name)
        try:
            ureg = _get_pint_ureg()
            if target_unit is not None:
                qty = ureg.Quantity(new_si_val, target_unit)
            else:
                # Try to parse orig_unit_str to know which SI unit this is.
                orig_m = _UNIT_STRING_RE.match(orig_text)
                if orig_m:
                    orig_qty = ureg.Quantity(float(orig_m.group(1)), orig_m.group(2))
                    base_unit = str(orig_qty.to_base_units().units)
                    qty = ureg.Quantity(new_si_val, base_unit)
                else:
                    return None
            converted = qty.to(orig_unit_str)
            magnitude = converted.magnitude
            formatted = f"{magnitude:g} {orig_unit_str}"
            return formatted
        except Exception as exc:
            warnings.append(
                f"Unit back-conversion failed for '{path_label}': {exc}. "
                f"Falling back to SI float."
            )
            return None

    def _apply_to_item(node: Any, item_id: Optional[str], path: tuple) -> None:
        """Recursively walk *node* and replace unit scalars in place."""
        if isinstance(node, dict):
            for k in list(node.keys()):
                child_path = path + (k,)
                map_key = (item_id, child_path)
                if map_key in unit_map:
                    orig_text, orig_unit_str, orig_si, scalar_cls = unit_map[map_key]
                    # Get the current SI value from the updated config.
                    current_si = _get_si_value(item_id, child_path)
                    if current_si is None:
                        # Can't determine new value — restore original text.
                        node[k] = orig_text
                        continue
                    if math.isclose(current_si, orig_si, rel_tol=1e-9):
                        # Unchanged — restore verbatim original.
                        node[k] = orig_text
                    else:
                        path_label = ".".join(str(p) for p in (item_id,) + child_path if p)
                        replacement = _make_replacement(
                            orig_text, orig_unit_str, current_si, scalar_cls, path_label
                        )
                        if replacement is not None:
                            try:
                                # Use the original scalar subclass for quoting.
                                node[k] = scalar_cls(replacement)
                            except Exception:
                                node[k] = replacement
                        # On failure, _make_replacement already appended a warning;
                        # leave the bare SI float as-is.
                else:
                    _apply_to_item(node[k], item_id, child_path)
        elif isinstance(node, list):
            for item in node:
                if isinstance(item, dict) and "id" in item:
                    _apply_to_item(item, item["id"], ())
                else:
                    _apply_to_item(item, item_id, path)

    _apply_to_item(merged_tree, None, ())
    return warnings

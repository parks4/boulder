"""Utility functions for the Boulder application."""

import re
from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# Unit coercion helpers
# ---------------------------------------------------------------------------

#: Matches strings of the form "number unit", e.g. "25 degC", "470 kg/d".
#: Group 1: the numeric part (including optional sign and exponent).
#: Group 2: the unit part (everything after the whitespace separator).
#: Plain numbers without a trailing unit do NOT match (backward-compatible).
_UNIT_STRING_RE = re.compile(
    r"^\s*([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)\s+(\S.*?)\s*$",
)


def _normalize_unit_string(val: str) -> str:
    """Normalize Unicode punctuation so Pint can parse common unit spellings.

    Handles minus signs, non-breaking spaces, and degree Celsius/Fahrenheit
    spellings that appear in user-authored YAML (copy-paste from word
    processors).
    """
    v = val.replace("\u00a0", " ").replace("\u202f", " ")
    for ch in ("\u2212", "\u2013", "\u2014", "\ufe63", "\uff0d"):
        v = v.replace(ch, "-")
    v = v.replace("\u2103", "degC")  # ℃
    v = v.replace("\u2109", "degF")  # ℉
    v = v.replace("\u00b0C", "degC").replace("\u00b0F", "degF")
    v = v.replace("°C", "degC").replace("°F", "degF")
    return v.strip()


#: Property-name → preferred target Pint unit.
#: Temperature maps to "kelvin" because Cantera's TPX setter expects K.
#: electric_power_kW uses "kilowatt" for backward-compatible kW storage.
_PROPERTY_UNIT_HINTS: Dict[str, str] = {
    "temperature": "kelvin",
    "pressure": "pascal",
    "dt": "second",
    "end_time": "second",
    "max_time": "second",
    "electric_power_kW": "kilowatt",
}

_pint_ureg: Optional[Any] = None  # lazy singleton


def _get_pint_ureg() -> Any:
    """Return (and lazily create) the shared Pint UnitRegistry."""
    global _pint_ureg
    if _pint_ureg is None:
        import pint  # noqa: PLC0415

        _pint_ureg = pint.UnitRegistry()
    return _pint_ureg


def coerce_unit_string(val: Any, property_name: str = "") -> Any:
    """Convert a string with embedded units to its canonical SI float.

    Only acts on strings of the form ``"number unit"``
    (e.g. ``"25 degC"``, ``"1.3 bar"``, ``"470 kg/d"``). Plain numeric
    values (``float`` / ``int``) and non-unit strings are returned unchanged,
    preserving backward compatibility with existing YAML configs that already
    store SI values as bare numbers.

    The conversion target is SI unless overridden by
    :data:`_PROPERTY_UNIT_HINTS`. Temperature always becomes **Kelvin** so
    that values feed directly into Cantera's ``TPX`` setter.

    Pint's ``OffsetUnitCalculusError`` (raised for degC / degF when the
    value is constructed from a plain string) is avoided by separating the
    numeric and unit parts with a regex and constructing
    ``pint.Quantity(number, unit)`` explicitly.

    If the string matches the ``number + unit`` pattern but Pint cannot parse
    the unit, a :class:`ValueError` is raised (no silent pass-through of bad
    unit strings).

    Parameters
    ----------
    val:
        Raw value read from a YAML config node.
    property_name:
        YAML key associated with *val*, used to look up the preferred
        target unit (e.g. ``"temperature"`` → ``"kelvin"``).

    Returns
    -------
    float | Any
        SI magnitude when a unit string was detected and parsed; the
        original *val* otherwise when the pattern does not match.
    """
    if not isinstance(val, str):
        return val
    val_norm = _normalize_unit_string(val)
    m = _UNIT_STRING_RE.match(val_norm)
    if not m:
        return val

    num_str, unit_str = m.group(1), m.group(2)
    target_unit_name: Optional[str] = _PROPERTY_UNIT_HINTS.get(property_name)
    ureg = _get_pint_ureg()
    # Construct Quantity(number, unit) explicitly to avoid Pint's
    # OffsetUnitCalculusError for offset units like degC / degF.
    try:
        qty = ureg.Quantity(float(num_str), unit_str)
        if target_unit_name is not None:
            return float(qty.to(target_unit_name).magnitude)
        return float(qty.to_base_units().magnitude)
    except Exception as exc:
        raise ValueError(
            f"Could not parse unit string {val!r} (property {property_name!r}): {exc}"
        ) from exc


def coerce_config_units(obj: Any, _key: str = "") -> Any:
    """Recursively coerce unit-bearing string values in a config to SI floats.

    Walks dicts and lists **in-place**, applying :func:`coerce_unit_string`
    to every leaf value.  Compatible with both plain ``dict`` / ``list``
    objects and ``ruamel.yaml`` ``CommentedMap`` / ``CommentedSeq``
    (comments are preserved because mutation is in-place).

    Parameters
    ----------
    obj:
        Configuration object (dict, list, or scalar).  Modified in-place
        when *obj* is a dict or list.
    _key:
        YAML key associated with *obj*; threaded through to
        :func:`coerce_unit_string` for property-name hints.

    Returns
    -------
    Any
        The same *obj* reference with unit strings replaced by SI floats.
    """
    if isinstance(obj, dict):
        for k, v in obj.items():
            # `metadata:` is descriptive free text (title, assumptions, author, …),
            # never unit-bearing — don't try to parse e.g. "2 torches…" as a unit.
            if k == "metadata":
                continue
            obj[k] = coerce_config_units(v, _key=k)
        return obj
    if isinstance(obj, list):
        for i, item in enumerate(obj):
            obj[i] = coerce_config_units(item, _key=_key)
        return obj
    return coerce_unit_string(obj, property_name=_key)


def get_sankey_theme_config(theme: str = "light") -> Dict[str, Any]:
    """Get theme-specific Sankey diagram configuration."""
    if theme == "dark":
        return {
            "paper_bgcolor": "#1a1a1a",
            "plot_bgcolor": "#2d2d2d",
            "font": {"color": "#ffffff", "size": 12},
            "title": {"font": {"color": "#ffffff"}},
            "node_colors": {
                "default": "#4A90E2",
                "reservoir": "#7ED321",
                "reactor": "#F5A623",
            },
            "link_colors": {
                "mass": "#B0B0B0",  # gray
                "enthalpy": "#4A90E2",  # blue
                "H2": "#B481FF",  # purple
                "CH4": "#6828B4",  # dark purple
                "heat": "#D3D3D3",  # light gray
                "Cs": "#666666",  # gray
            },
        }
    else:  # light theme
        return {
            "paper_bgcolor": "#ffffff",  # white
            "plot_bgcolor": "#ffffff",  # white
            "font": {"color": "#212529", "size": 12},
            "title": {"font": {"color": "#212529"}},
            "node_colors": {
                "default": "#1f77b4",  # blue
                "reservoir": "#2ca02c",  # green
                "reactor": "#ff7f0e",  # orange
            },
            "link_colors": {
                "mass": "pink",  # pink
                "enthalpy": "purple",  # purple
                "H2": "#B481FF",  # purple
                "CH4": "#6828B4",  # dark purple
                "heat": "#D3D3D3",  # light gray
                "Cs": "#000000",  # black
            },
        }

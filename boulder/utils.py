"""Utility functions for the Boulder application."""

import re
from functools import lru_cache
from typing import Any, Dict, List, Optional

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
    try:
        ureg = _get_pint_ureg()
        # Construct Quantity(number, unit) explicitly to avoid Pint's
        # OffsetUnitCalculusError for offset units like degC / degF.
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
            obj[k] = coerce_config_units(v, _key=k)
        return obj
    if isinstance(obj, list):
        for i, item in enumerate(obj):
            obj[i] = coerce_config_units(item, _key=_key)
        return obj
    return coerce_unit_string(obj, property_name=_key)


def config_to_cyto_elements(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Convert configuration to Cytoscape elements.

    - Reactors and reservoirs become nodes
    - Connections become edges
    - Optional grouping: if a component property `group` (or `group_name`) is set,
      components sharing the same group appear inside a compound parent node.
    """
    elements: List[Dict[str, Any]] = []

    # Track created parent (group) nodes to avoid duplicates
    created_groups: set[str] = set()

    # Add nodes (reactors)
    for node in config.get("nodes", []):
        properties = node.get("properties", {})

        # Determine group (if any) from properties
        group_name = (
            str(properties.get("group", ""))
            if properties.get("group") is not None
            else str(properties.get("group_name", ""))
        )
        group_name = group_name.strip()

        # If grouped, ensure a parent compound node exists
        if group_name:
            parent_id = f"group:{group_name}"
            if parent_id not in created_groups:
                created_groups.add(parent_id)
                elements.append(
                    {
                        "data": {
                            "id": parent_id,
                            "label": group_name,
                            "isGroup": True,
                        }
                    }
                )

        node_data: Dict[str, Any] = {
            "id": node["id"],
            "label": node["id"],
            "type": node["type"],
            "properties": properties,
        }

        # Attach parent if grouped
        if group_name:
            node_data["parent"] = f"group:{group_name}"
            node_data["group"] = group_name

        # Flatten commonly used properties for Cytoscape mapping
        # This allows Cytoscape selectors like "mapData(temperature, ...)" to work
        if "temperature" in properties:
            node_data["temperature"] = properties["temperature"]
        if "pressure" in properties:
            node_data["pressure"] = properties["pressure"]
        if "composition" in properties:
            node_data["composition"] = properties["composition"]
        if "volume" in properties:
            node_data["volume"] = properties["volume"]

        elements.append({"data": node_data})

    # Add edges (connections)
    for connection in config.get("connections", []):
        properties = connection.get("properties", {})
        edge_data: Dict[str, Any] = {
            "id": connection["id"],
            "source": connection["source"],
            "target": connection["target"],
            "label": connection["type"],
            "type": connection["type"],  # Add type field for consistency
            "properties": properties,
        }

        # Flatten commonly used properties for Cytoscape mapping
        if "mass_flow_rate" in properties:
            edge_data["mass_flow_rate"] = properties["mass_flow_rate"]
        if "valve_coeff" in properties:
            edge_data["valve_coeff"] = properties["valve_coeff"]

        elements.append({"data": edge_data})

    return elements


@lru_cache(maxsize=1)
def get_available_cantera_mechanisms() -> List[Dict[str, str]]:
    """Get all available Cantera mechanism files from data directories.

    Returns
    -------
        List of dictionaries with 'label' and 'value' keys for dropdown options.
    """
    from pathlib import Path

    import cantera as ct

    mechanisms = []

    # Get Cantera data directories
    try:
        data_dirs = ct.get_data_directories()
    except AttributeError:
        # Fallback for older Cantera versions
        cantera_dir = Path(ct.__file__).parent
        data_dirs = [str(cantera_dir / "data")]

    # Scan for YAML mechanism files
    yaml_files: set[Path] = set()
    for data_dir in data_dirs:
        data_path = Path(data_dir)
        if data_path.exists():
            # Look for .yaml and .yml files
            for ext in ["*.yaml", "*.yml"]:
                yaml_files.update(data_path.glob(ext))

    # Convert to dropdown options, excluding some internal/test files
    exclude_patterns = [
        "test",
        "example",
        "tutorial",
        "sample",
        "demo",
        "validation",
        "transport",
        "pre-commit",
        "config",
        "template",
        "species",
        "thermo",
    ]

    # Use a set to track filenames and avoid duplicates
    seen_filenames = set()

    for yaml_file in sorted(yaml_files):
        filename = yaml_file.name

        # Skip duplicates based on filename
        if filename in seen_filenames:
            continue

        # Skip files that match exclude patterns or don't seem like mechanism files
        if any(pattern in filename.lower() for pattern in exclude_patterns):
            continue

        # Skip files that are clearly not mechanism files (dot files, etc)
        if filename.startswith(".") or len(filename) < 5:
            continue

        # Skip duplicate filenames (same file in multiple directories)
        if filename in seen_filenames:
            continue

        # Mark this filename as seen
        seen_filenames.add(filename)

        # Create a readable label
        label = filename.replace(".yaml", "").replace(".yml", "").replace("_", " ")
        label = " ".join(word.capitalize() for word in label.split())

        # Add special descriptions for known mechanisms
        if filename == "gri30.yaml":
            label = "GRI 3.0 (Natural Gas Combustion)"
        elif filename == "h2o2.yaml":
            label = "H2/O2 (Hydrogen Combustion)"
        elif filename == "air.yaml":
            label = "Air (Ideal Gas Properties)"
        elif "methane" in filename.lower():
            label += " (Methane)"
        elif "hydrogen" in filename.lower():
            label += " (Hydrogen)"
        elif "ethane" in filename.lower():
            label += " (Ethane)"

        mechanisms.append({"label": label, "value": filename})

    return mechanisms


def label_with_unit(key: str) -> str:
    """Add units to property labels for display."""
    unit_map = {
        "pressure": "pressure (Pa)",
        "composition": "composition (%mol)",
        "temperature": "temperature (°C)",
        "mass_flow_rate": "mass flow rate (kg/s)",
        "volume": "volume (m³)",
        "valve_coeff": "valve coefficient (-)",
    }
    return unit_map.get(key, key)


# Plot theme utilities
def get_plotly_theme_template(theme: str = "light") -> Dict[str, Any]:
    """Get Plotly theme template based on the current theme."""
    if theme == "dark":
        return {
            "layout": {
                "paper_bgcolor": "#1a1a1a",
                "plot_bgcolor": "#2d2d2d",
                "font": {"color": "#eaeaea"},
                "title": {"font": {"color": "#f7f7f7", "size": 16}},
                "xaxis": {
                    "gridcolor": "#404040",
                    "zerolinecolor": "#404040",
                    "tickcolor": "#eaeaea",
                    "title": {"font": {"color": "#eaeaea", "size": 12}},
                    "tickfont": {"color": "#eaeaea"},
                },
                "yaxis": {
                    "gridcolor": "#404040",
                    "zerolinecolor": "#404040",
                    "tickcolor": "#eaeaea",
                    "title": {"font": {"color": "#eaeaea", "size": 12}},
                    "tickfont": {"color": "#eaeaea"},
                },
                "legend": {
                    "font": {"color": "#eaeaea"},
                    "bgcolor": "rgba(45, 45, 45, 0.8)",
                    "bordercolor": "#404040",
                },
                "colorway": [
                    "#4A90E2",  # Blue
                    "#7ED321",  # Green
                    "#F5A623",  # Orange
                    "#D0021B",  # Red
                    "#9013FE",  # Purple
                    "#50E3C2",  # Cyan
                    "#BD10E0",  # Magenta
                    "#B8E986",  # Light Green
                    "#FF6B6B",  # Light Red
                    "#4ECDC4",  # Teal
                ],
                "hovermode": "closest",
                "hoverlabel": {
                    "bgcolor": "#2d2d2d",
                    "font": {"color": "#ffffff"},
                    "bordercolor": "#404040",
                },
            }
        }
    else:  # light theme
        return {
            "layout": {
                "paper_bgcolor": "#ffffff",
                "plot_bgcolor": "#ffffff",
                "font": {"color": "#212529"},
                "title": {"font": {"color": "#212529"}},
                "xaxis": {
                    "gridcolor": "#dee2e6",
                    "zerolinecolor": "#dee2e6",
                    "tickcolor": "#212529",
                    "title": {"font": {"color": "#212529"}},
                    "tickfont": {"color": "#212529"},
                },
                "yaxis": {
                    "gridcolor": "#dee2e6",
                    "zerolinecolor": "#dee2e6",
                    "tickcolor": "#212529",
                    "title": {"font": {"color": "#212529"}},
                    "tickfont": {"color": "#212529"},
                },
                "legend": {
                    "font": {"color": "#212529"},
                    "bgcolor": "rgba(255, 255, 255, 0.8)",
                    "bordercolor": "#dee2e6",
                },
                "colorway": [
                    "#1f77b4",  # Blue
                    "#ff7f0e",  # Orange
                    "#2ca02c",  # Green
                    "#d62728",  # Red
                    "#9467bd",  # Purple
                    "#8c564b",  # Brown
                    "#e377c2",  # Pink
                    "#7f7f7f",  # Gray
                    "#bcbd22",  # Olive
                    "#17becf",  # Cyan
                ],
                "hovermode": "closest",
                "hoverlabel": {
                    "bgcolor": "#ffffff",
                    "font": {"color": "#212529"},
                    "bordercolor": "#dee2e6",
                },
            }
        }


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


def apply_theme_to_figure(fig, theme: str = "light"):
    """Apply theme to a Plotly figure."""
    theme_config = get_plotly_theme_template(theme)
    fig.update_layout(**theme_config["layout"])
    return fig

"""Shared helpers for STONE node ``energy`` property on Cantera reactors."""

from __future__ import annotations

from typing import Any, Literal, Tuple

import cantera as ct

EnergyMode = Literal["on", "off"]

_ENERGY_REACTOR_CLASSES: tuple[type, ...] = (
    ct.IdealGasReactor,
    ct.ConstPressureReactor,
    ct.IdealGasConstPressureReactor,
    ct.IdealGasConstPressureMoleReactor,
    ct.IdealGasMoleReactor,
)


def parse_energy_prop(props: dict[str, Any]) -> Tuple[EnergyMode | None, bool]:
    """Return ``(energy, explicitly_set)``. Absent key → ``(None, False)``."""
    if "energy" not in props:
        return None, False
    energy_val = props["energy"]
    if isinstance(energy_val, bool):
        return ("off" if not energy_val else "on"), True
    if str(energy_val).lower() in ("off", "false", "0"):
        return "off", True
    return "on", True


def supports_energy_kwarg(reactor_cls: type) -> bool:
    """Return True when *reactor_cls* accepts ``energy=`` in its constructor."""
    return reactor_cls in _ENERGY_REACTOR_CLASSES or hasattr(
        reactor_cls, "energy_enabled"
    )


def validate_explicit_energy(
    props: dict[str, Any], reactor_cls: type, type_name: str
) -> None:
    """Raise if ``energy`` is set explicitly on an unsupported reactor type."""
    _, explicit = parse_energy_prop(props)
    if explicit and not supports_energy_kwarg(reactor_cls):
        raise ValueError(
            f"Node property 'energy' is not supported for reactor type "
            f"{type_name!r}. Remove 'energy' or choose a reactor that implements "
            f"an energy equation (e.g. IdealGasConstPressureMoleReactor)."
        )


def validate_energy_on_built_reactor(
    reactor: ct.Reactor, props: dict[str, Any], type_name: str
) -> None:
    """Raise if YAML set ``energy`` on a built reactor that cannot honour it."""
    _, explicit = parse_energy_prop(props)
    if not explicit:
        return
    if not hasattr(reactor, "energy_enabled"):
        raise ValueError(
            f"Node property 'energy' is not supported for reactor type "
            f"{type_name!r}. Remove 'energy' or choose a reactor that implements "
            f"an energy equation (e.g. IdealGasConstPressureMoleReactor)."
        )


def build_reactor_with_energy(
    reactor_cls: type,
    gas: ct.Solution,
    *,
    props: dict[str, Any],
    clone: bool,
    type_name: str,
) -> ct.Reactor:
    """Instantiate *reactor_cls* with optional ``energy`` from node properties."""
    validate_explicit_energy(props, reactor_cls, type_name)
    energy, _ = parse_energy_prop(props)
    kwargs: dict[str, Any] = {"clone": clone}
    if energy is not None:
        kwargs["energy"] = energy
    return reactor_cls(gas, **kwargs)


def energy_ctor_suffix(props: dict[str, Any]) -> str:
    r"""Return ``', energy=\"on\"'`` / ``', energy=\"off\"'`` or empty for emitters."""
    energy, explicit = parse_energy_prop(props)
    if not explicit or energy is None:
        return ""
    return f", energy={energy!r}"

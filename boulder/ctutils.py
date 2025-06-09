"""Util functions to handle the Cantera package."""

import inspect
from pathlib import Path

import cantera as ct
import numpy as np
import pandas as pd


def get_mechanism_path(mechanism_str) -> str:
    """Return path (str) of Cantera mechanism.

    Mechanism is looked up from (in order):

    1. An absolute path (if exists) or relative path from the working directory
    2. A relative path from the calling script's folder.
    3. The /cantera/data directory

    Mechanism can then be fed to a :py:class:`cantera.Solution` object.

    Examples
    --------

    .. minigallery:: bloc.utils.get_mechanism_path
    """
    mechanism = Path(mechanism_str)

    # 1. Assume it's a relative or absolute path
    if mechanism.exists():
        return str(mechanism.absolute())

    # 2. Look up in the calling script's folder

    # ... get calling directory
    calling_dir = Path(inspect.stack()[1][1]).parent
    mechanism = calling_dir / str(mechanism_str)

    # ... If exists, returns :
    if mechanism.exists():
        return str(mechanism.absolute())

    # 3. Look up from the cantera/data directory
    import cantera as ct

    cantera_dir = Path(ct.__file__).parent
    mechanism = cantera_dir / "data" / str(mechanism_str)

    if mechanism.exists():
        return str(mechanism.absolute())

    # Else
    raise FileNotFoundError(
        f"Mechanism {mechanism} not found in working directory ({Path('').absolute()}) neither in calling "
        f"directory ({calling_dir})"
    )


def collect_all_reactors_and_reservoirs(sim):
    """Collect all Reactors and Reservoirs in a Network.

    Parameters
    ----------
    sim : cantera.ReactorNet

    Returns
    -------
    set of cantera.Reactor
    """
    # @dev: initial code taken from https://github.com/Cantera/cantera/blob/0720efb02d6e2be83794346d522f0872381aa972/interfaces/cython/cantera/drawnetwork.py#L97  # noqa: E501
    # as there was no collect() function clearly available in Cantera

    # collect elements as set to avoid duplicates
    reactors = set(sim.reactors)
    flow_controllers = set()
    walls = set()
    drawn_reactors = set()

    reactor_groups = {}
    for r in reactors:
        if r.group_name not in reactor_groups:
            reactor_groups[r.group_name] = set()
        reactor_groups[r.group_name].add(r)

    reactor_groups.pop("", None)
    if reactor_groups:
        for name, group in reactor_groups.items():
            for r in group:
                drawn_reactors.add(r)
                flow_controllers.update(r.inlets + r.outlets)
                walls.update(r.walls)
    reactors -= drawn_reactors

    for r in reactors:
        flow_controllers.update(r.inlets + r.outlets)
        walls.update(r.walls)

    # some Reactors or Reservoirs only exist as connecting nodes
    connected_reactors = set()
    for fc in flow_controllers:
        connected_reactors.update((fc.upstream, fc.downstream))
    for w in walls:
        connected_reactors.update((w.left_reactor, w.right_reactor))

    # ensure that all names are unique
    all_reactors = reactors | connected_reactors
    names = set([r.name for r in all_reactors])
    assert len(names) == len(all_reactors), (
        "All reactors must have unique names when drawn."
    )

    return all_reactors


def heating_values(fuel, mechanism="gri30.yaml", return_unit="J/kg"):
    """Return the Lower & Higher heating values (LHV, HHV) for the specified fuel, in J/kg.

    References: https://cantera.org/examples/jupyter/thermo/heating_value.ipynb.html

    Parameters
    ----------
    mechanism: str, optional
        kinetic mechanism including the thermodynamic data used to do the calculations.
        Uses schem.config['mechanism'] if not given

    If O2 is not defined in mechanism, return nan.

    Notes
    -----
    @Jean: Warning, according to Wikipedia, there are several definition of LHV. Here, we assume
    that water condensation energy is not recovered, but heat is recovered down to 25°C. Another
    widespread defintion considers that the products are cooled to 150°C --> no water condensation,
    nor heat recovery below 150°C.
    """
    # TODO: validate we get correct LHV; HHV values; add a test for known fuels.
    mechanism_path = get_mechanism_path(mechanism)

    gas = ct.Solution(mechanism_path)
    gas.TP = 298, ct.one_atm
    try:
        gas.set_equivalence_ratio(1.0, fuel.mole_fraction_dict(), "O2:1.0")
    except ct._utils.CanteraError as err:
        if "Unknown species 'O2'" in str(err):
            # ignore and return nan
            return np.nan, np.nan
    h1 = gas.enthalpy_mass
    Y_fuel = sum([gas[f].Y[0] for f in list(fuel.mole_fraction_dict().keys())])

    # complete combustion products
    X_products = {
        "CO2": gas.elemental_mole_fraction("C"),
        "H2O": 0.5 * gas.elemental_mole_fraction("H"),
        "N2": 0.5 * gas.elemental_mole_fraction("N"),
    }

    # Get water properties (to compute HHV)
    water = ct.Water()
    # Set liquid water state, with vapor fraction x = 0
    water.TQ = 298, 0
    h_liquid = water.h
    # Set gaseous water state, with vapor fraction x = 1
    water.TQ = 298, 1
    h_gas = water.h

    gas.TPX = None, None, X_products
    Y_H2O = gas["H2O"].Y[0]
    h2 = gas.enthalpy_mass
    LHV = -(h2 - h1) / Y_fuel
    HHV = -(h2 - h1 + (h_liquid - h_gas) * Y_H2O) / Y_fuel

    if return_unit != "J/kg":
        raise NotImplementedError(f"return_unit: {return_unit}")

    return LHV, HHV


def get_STP_properties_IUPAC(g):
    """Get density and enthalpy under Standard Temperature & Pressure (STP).

    Here STP is defined as :

    - 0°C (273.15 K), 1 bar (100 kPa), according to STP by IUPAC (>=1982)

    It should not be confused with :

    - 0°C (273.15 K), 1 atm (101.325 kPa):  as in STP by IUPAC (before 1982) and as in
                DIN 1343, used as the base value for defining the standard cubic meter.
    - 15°C (288.15 K), 1 atm (101.325 kPa):  as in ISO 2533 conditions
    - 20°C (293.15 K), 1 atm (101.325 kPa), as in Normal (NTP) conditions by NIST

    References
    ----------
    https://en.wikipedia.org/wiki/Standard_temperature_and_pressure.
    """
    T, P, X = g.TPX
    try:
        g.TPX = 273.15, 1e5, X
        density_STP = g.density
        enthalpy_STP = g.enthalpy_mass
    finally:
        # reset as expected
        g.TPX = T, P, X

    return density_STP, enthalpy_STP


def get_NTP_properties_NIST(g):
    """Get density and enthalpy under Normal Temperature & Pressure (NTP).

    Here NTP is defined as :

    - 20°C (293.15 K), 1 atm (101.325 kPa), according to NTP by NIST

    It should not be confused with :

    - 0°C (273.15 K), 1 bar (100 kPa), according to STP by IUPAC (>=1982)
    - 0°C (273.15 K), 1 atm (101.325 kPa):  as in STP by IUPAC (before 1982) and as in
                DIN 1343, used as the base value for defining the standard cubic meter.
    - 15°C (288.15 K), 1 atm (101.325 kPa):  as in ISO 2533 conditions

    References
    ----------
    https://en.wikipedia.org/wiki/Standard_temperature_and_pressure.

    See Also
    --------
    :py:
    """
    T, P, X = g.TPX
    try:
        g.TPX = 293.15, ct.one_atm, X
        density_STP = g.density
        enthalpy_STP = g.enthalpy_mass
    finally:
        # reset as expected
        g.TPX = T, P, X

    return density_STP, enthalpy_STP


def get_gas_phase_composition(
    compo_dict, solid_sp=["C(s)", "BIN", "A37", "C(soot)", "CSOLID"], prefix="X"
):
    """Return the gas phase composition by removing solid species and renormalising the mole/mass fractions.

    Parameters
    ----------
        compo_dict : dict
            dictionary of species mole/mass fractions

        solid_sp : list
            list of solid species to exclude from the gas phase.

        prefix : str
            prefix for the output species names.
            Convention: X for mole fractions, Y for mass fractions.
    """
    n_tot = 0
    n_dict = {}
    for s, n_s in compo_dict.items():
        s_is_solid = False
        for solid in solid_sp:
            if solid in s:
                s_is_solid = True

        if s_is_solid:
            # print(f'{s} is solid')
            continue

        n_tot += n_s
        n_dict[f"{prefix}_{s}"] = n_s

    # Guard against division by zero if all species are filtered out
    if n_tot == 0:
        # Return an empty Series if no non-solid species are found
        return pd.Series(dtype=float)

    return pd.Series(n_dict).sort_values(ascending=False) / n_tot

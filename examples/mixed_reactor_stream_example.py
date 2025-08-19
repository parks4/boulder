"""Mixing two streams example.

The Cantera example https://cantera.org/3.1/examples/python/reactors/mix1.html,
used here to be converted to a 🪨 STONE serialized .yaml format with
:py:func:`boulder.sim2stone.sim_to_stone_yaml`

Since reactors can have multiple inlets and outlets, they can be used to
implement mixers, splitters, etc. In this example, air and methane are mixed
in stoichiometric proportions. Due to the low temperature, no reactions occur.
Note that the air stream and the methane stream use different reaction
mechanisms, with different numbers of species and reactions. When gas flows
from one reactor or reservoir to another one with a different reaction
mechanism, species are matched by name. If the upstream reactor contains a
species that is not present in the downstream reaction mechanism, it will be
ignored. In general, reaction mechanisms for downstream reactors should
contain all species that might be present in any upstream reactor.
"""

import cantera as ct

# For regeneration (see end of file)
from boulder.cantera_converter import CanteraConverter
from boulder.config import load_config_file, normalize_config, validate_config

# %%
# Boulder addition
# ----------------
# For conversion:
from boulder.sim2stone import write_sim_as_yaml

# %%
# Set up the reactor network
# --------------------------
#
# Use air for stream a.
gas_a = ct.Solution("air.yaml")
gas_a.TPX = 300.0, ct.one_atm, "O2:0.21, N2:0.78, AR:0.01"
rho_a = gas_a.density

# %%
# Use GRI-Mech 3.0 for stream b (methane) and for the mixer. If it is desired
# to have a pure mixer, with no chemistry, use instead a reaction mechanism
# for gas_b that has no reactions.
gas_b = ct.Solution("gri30.yaml")
gas_b.TPX = 300.0, ct.one_atm, "CH4:1"
rho_b = gas_b.density

# %%
# Create reservoirs for the two inlet streams and for the outlet stream.  The
# upstream reservoirs could be replaced by reactors, which might themselves be
# connected to reactors further upstream. The outlet reservoir could be
# replaced with a reactor with no outlet, if it is desired to integrate the
# composition leaving the mixer in time, or by an arbitrary network of
# downstream reactors.
res_a = ct.Reservoir(gas_a, name="Air Reservoir")
res_b = ct.Reservoir(gas_b, name="Fuel Reservoir")
downstream = ct.Reservoir(gas_a, name="Outlet Reservoir")

# %%
# Create a reactor for the mixer. A reactor is required instead of a
# reservoir, since the state will change with time if the inlet mass flow
# rates change or if there is chemistry occurring.
gas_b.TPX = 300.0, ct.one_atm, "O2:0.21, N2:0.78, AR:0.01"
mixer = ct.IdealGasReactor(gas_b, name="Mixer")

# %%
# Create two mass flow controllers connecting the upstream reservoirs to the
# mixer, and set their mass flow rates to values corresponding to
# stoichiometric combustion.
mfc1 = ct.MassFlowController(res_a, mixer, mdot=rho_a * 2.5 / 0.21, name="Air Inlet")
mfc2 = ct.MassFlowController(res_b, mixer, mdot=rho_b * 1.0, name="Fuel Inlet")

# %%
# Connect the mixer to the downstream reservoir with a valve.
outlet = ct.Valve(mixer, downstream, K=10.0, name="Valve")

sim = ct.ReactorNet([mixer])

# %%
# Get the mixed state
# -------------------
#
# Since the mixer is a reactor, we need to integrate in time to reach steady state.
sim.advance_to_steady_state()

# view the state of the gas in the mixer
print(mixer.thermo.report())

# %%
# Show the network structure
# --------------------------
try:
    diagram = sim.draw(print_state=True, species="X")
except ImportError as err:
    print(f"Unable to show network structure:\n{err}")

# %%
# Boulder additions
# -----------------

# Serialize the network to a STONE YAML file
output_yaml = "mixed_reactor_stream.yaml"
write_sim_as_yaml(sim, output_yaml, default_mechanism="gri30.yaml")
print(f"Wrote STONE YAML to {output_yaml}")

# ✨ We now have a STONE YAML representation of the simulation!

# %%
# The other way around:
# ---------------------
# Regenerate the simulation from the STONE YAML file


# Write the simulation as a STONE YAML file
write_sim_as_yaml(sim, "mixed_reactor_stream.yaml", default_mechanism="gri30.yaml")

# Now regenerate the network from the YAML file, and verify it is runnable
loaded = load_config_file("mixed_reactor_stream.yaml")
normalized = normalize_config(loaded)
validated = validate_config(normalized)
# Get mechanism from phases.gas.mechanism (STONE standard)
phases = validated.get("phases", {})
gas = phases.get("gas", {}) if isinstance(phases, dict) else {}
mechanism = gas.get("mechanism", "gri30.yaml")
converter = CanteraConverter(mechanism=mechanism)
network, results = converter.build_network(validated)
print(
    f"Rebuilt network with {len(converter.reactors)} nodes and "
    f"{len(converter.connections)} connections."
)

# %% Compare the new network to the original
expected_nodes = {res_a.name, res_b.name, mixer.name, downstream.name}
assert set(converter.reactors.keys()) == expected_nodes
assert len(converter.connections) == 3

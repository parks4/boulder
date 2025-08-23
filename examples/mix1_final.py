"""
Converted from mix1.py

Mixing two streams
==================

*A Cantera example (from https://cantera.org/3.1/examples/python/reactors/mix1.html
used in Boulder to showcase the sim2stone functionality: generating a simulation
yaml file from a :py:class:`~cantera.ReactorNet` object*

Since reactors can have multiple inlets and outlets, they can be used to
implement mixers, splitters, etc. In this example, air and methane are mixed
in stoichiometric proportions. Due to the low temperature, no reactions occur.
Note that the air stream and the methane stream use *different* reaction
mechanisms, with different numbers of species and reactions. When gas flows
from one reactor or reservoir to another one with a different reaction
mechanism, species are matched by name. If the upstream reactor contains a
species that is not present in the downstream reaction mechanism, it will be
ignored. In general, reaction mechanisms for downstream reactors should
contain all species that might be present in any upstream reactor.

Compare this approach for the transient problem to the method used for the
steady-state problem in :doc:`mixing.py <../thermo/mixing>`.

Requires: cantera >= 3.1.0, graphviz

.. tags:: Python, thermodynamics, reactor network, mixture
"""

# Import Cantera for chemical kinetics and reactor modeling
import cantera as ct

# Load the chemical mechanism (contains species and reactions)
gas_default = ct.Solution('gri30.yaml')

# ===== REACTOR SETUP =====
# Create Reservoir 'Air Reservoir' - infinite capacity, constant state
# Fixed conditions: T=300.0K, P=101325.00000000003Pa, composition='N2:0.78,O2:0.21,AR:0.01'
Air_Reservoir = ct.Reservoir(gas_default)
Air_Reservoir.name = 'Air Reservoir'
# Create Reservoir 'Fuel Reservoir' - infinite capacity, constant state
# Fixed conditions: T=300.0K, P=101325.00000000001Pa, composition='CH4:1'
Fuel_Reservoir = ct.Reservoir(gas_default)
Fuel_Reservoir.name = 'Fuel Reservoir'
# Create IdealGasReactor 'Mixer' - variable volume, constant energy
# Initial conditions: T=299.9999999999867K, P=101326.46614484335Pa, composition='N2:0.719557,O2:0.193727,CH4:0.0774908,AR:0.00922509'
Mixer = ct.IdealGasReactor(gas_default)
Mixer.name = 'Mixer'
Mixer.volume = 1.0  # Set reactor volume in m³
Mixer.group_name = ''
# Create Reservoir 'Outlet Reservoir' - infinite capacity, constant state
# Fixed conditions: T=300.0K, P=101325.00000000003Pa, composition='N2:0.78,O2:0.21,AR:0.01'
Outlet_Reservoir = ct.Reservoir(gas_default)
Outlet_Reservoir.name = 'Outlet Reservoir'

# ===== CONNECTION SETUP =====
# Create MassFlowController 'Air Inlet': Air Reservoir -> Mixer
# Controls mass flow rate at 0.1 kg/s
Air_Inlet = ct.MassFlowController(Air_Reservoir, Mixer)
Air_Inlet.mass_flow_rate = 0.1
# Create MassFlowController 'Fuel Inlet': Fuel Reservoir -> Mixer
# Controls mass flow rate at 0.1 kg/s
Fuel_Inlet = ct.MassFlowController(Fuel_Reservoir, Mixer)
Fuel_Inlet.mass_flow_rate = 0.1
# Create Valve 'Valve': Mixer -> Outlet Reservoir
# Flow depends on pressure difference, valve coeff = 10.0
Valve = ct.Valve(Mixer, Outlet_Reservoir)
Valve.valve_coeff = 10.0

# ===== NETWORK SETUP =====
# Create reactor network with all time-evolving reactors
# Reactors in network: Mixer
network = ct.ReactorNet([Mixer])

# Set solver tolerances for numerical integration
network.rtol = 1e-6  # Relative tolerance
network.atol = 1e-8  # Absolute tolerance
network.max_steps = 10000  # Maximum steps per time step

# ===== SIMULATION EXECUTION =====
# Import numpy for time array generation
import numpy as np

# Create time array: 0 to 10.0s with 1.0s steps
times = np.arange(0, 10.0, 1.0)

# Run time integration loop
print('Starting simulation...')
print('Time (s)\tTemperatures (K)')
for t in times:
    # Advance the reactor network to time t
    network.advance(t)
    # Print current time and reactor temperatures
    print(f"t={t:.4f}, T={[r.thermo.T for r in network.reactors]}")

print('Simulation completed!')
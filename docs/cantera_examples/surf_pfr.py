r"""
Plug flow reactor with surface chemistry.

Plug flow reactor with surface chemistry
=========================================

This example solves a plug-flow reactor problem, where the chemistry is
surface chemistry. The specific problem simulated is the partial oxidation of
methane over a platinum catalyst in a packed bed reactor.

This example solves the DAE system directly, using the ``FlowReactor`` class
and the SUNDIALS IDA solver, in contrast to the approximation as a chain of
steady-state WSRs used in ``surf_pfr_chain.py``.

Requires: cantera >= 3.2.0

.. tags:: surface chemistry, reactor network, plug flow reactor

Boulder (this repository)
--------------------------

This file is a **vendored copy** of a `Cantera`_ Python example, kept under
``docs/cantera_examples/`` for documentation and CI, with one deliberate
deviation from the upstream source: the ``r.phase['CH4', 'H2', 'CO'].X``
species-subset print helper is replaced with plain ``species_index`` lookups.
That chained-indexing pattern raises ``ValueError: cannot resize an array
that references or is referenced by another array in this way`` on this
environment's Cantera/NumPy combination -- a pre-existing upstream/NumPy
interaction, not a Boulder issue. The reactor setup and physics are otherwise
unchanged. Upstream samples live in the `Cantera source tree`_.

From the repository root, with the ``boulder`` environment active::

    boulder docs/cantera_examples/surf_pfr.py

Headless conversion to STONE YAML::

    python -m boulder.cli docs/cantera_examples/surf_pfr.py --headless \\
        --output-yaml /path/to/out.yaml

.. _Cantera: https://cantera.org/stable/index.html
.. _Cantera source tree: https://github.com/Cantera/cantera/tree/main/samples/python
"""

import csv

import cantera as ct

# unit conversion factors to SI
cm = 0.01
minute = 60.0

# Input Parameters
tc = 800.0  # Temperature in Celsius
length = 0.3 * cm  # Catalyst bed length
area = 1.0 * cm**2  # Catalyst bed area
cat_area_per_vol = 1000.0 / cm  # Catalyst particle surface area per unit volume
velocity = 40.0 * cm / minute  # gas velocity
porosity = 0.3  # Catalyst bed porosity

# input file containing the surface reaction mechanism
yaml_file = "methane_pox_on_pt.yaml"
output_filename = "surf_pfr_output.csv"

t = tc + 273.15  # convert to Kelvin

# import the model and set the initial conditions
surf = ct.Interface(yaml_file, "Pt_surf")
surf.TP = t, ct.one_atm
gas = surf.adjacent["gas"]
gas.TPX = t, ct.one_atm, "CH4:1, O2:1.5, AR:0.1"

mass_flow_rate = velocity * gas.density * area * porosity

# create a new reactor
r = ct.FlowReactor(gas, clone=True)
r.area = area
r.surface_area_to_volume_ratio = cat_area_per_vol * porosity
r.mass_flow_rate = mass_flow_rate
r.energy_enabled = False

# Add the reacting surface to the reactor
rsurf = ct.ReactorSurface(surf, r, clone=True)

sim = ct.ReactorNet([r])

# %%
# Integrate along the length of the reactor
# ------------------------------------------
print_species = ["CH4", "H2", "CO"]
print_idx = [gas.species_index(s) for s in print_species]

output_data = []
n = 0
print("    distance       X_CH4        X_H2        X_CO")
X0 = r.phase.X
print(f"  {0.0:10f}  " + "  ".join(f"{X0[i]:10f}" for i in print_idx))

while sim.distance < length:
    dist = sim.distance * 1e3  # convert to mm
    sim.step()

    if n % 100 == 0 or (dist > 1 and n % 10 == 0):
        X = r.phase.X
        print(f"  {dist:10f}  " + "  ".join(f"{X[i]:10f}" for i in print_idx))
    n += 1

    # write the gas mole fractions and surface coverages vs. distance
    output_data.append(
        [dist, r.T - 273.15, r.phase.P / ct.one_atm]
        + list(r.phase.X)  # use r.phase.X not gas.X
        + list(rsurf.phase.coverages)  # use rsurf.phase.coverages not surf.coverages
    )

with open(output_filename, "w", newline="") as outfile:
    writer = csv.writer(outfile)
    writer.writerow(
        ["Distance (mm)", "T (C)", "P (atm)"] + gas.species_names + surf.species_names
    )
    writer.writerows(output_data)

print(f"Results saved to '{output_filename}'")
print("Simulation completed.")

import type { NodeConservation } from "@/types/simulation";

/**
 * True when the node's energy balance was checked (absent `energy_checked`
 * means checked): an imposed-temperature node reports `energy_checked: false`,
 * its imbalance being the heat the imposed temperature implies.
 */
export function energyChecked(c: NodeConservation): boolean {
  return c.energy_checked !== false;
}

/** True when a checked mass or energy balance fails to close. */
export function conservationFails(c: NodeConservation): boolean {
  return !c.mass_closes || (energyChecked(c) && !c.energy_closes);
}

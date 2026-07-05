/**
 * Unit conversion and formatting utilities for reactor properties.
 */

/**
 * Convert Celsius to Kelvin.
 */
export function celsiusToKelvin(celsius: number): number {
  return celsius + 273.15;
}

/**
 * Convert Kelvin to Celsius.
 */
export function kelvinToCelsius(kelvin: number): number {
  return kelvin - 273.15;
}

/**
 * Format a number with appropriate precision and thousands separators.
 * Very small or very large magnitudes fall back to scientific notation so
 * SI-stored values (e.g. 5e-4 m, 1e19 m^-3) stay readable.
 */
export function formatNumber(value: number, decimals: number = 2): string {
  const abs = Math.abs(value);
  if (value !== 0 && (abs < 0.01 || abs >= 1e6)) {
    return value.toExponential(3);
  }
  return value.toLocaleString("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

/**
 * Canonical display units for reactor/connection property keys.
 * Mirrors boulder/utils.py `_PROPERTY_UNIT_HINTS` (SI storage) plus a few
 * additional keys whose units are defined by convention in Cantera/Boulder.
 * Temperature is shown in °C because PropertiesPanel converts K→°C for display.
 */
const PROPERTY_DISPLAY_UNIT: Record<string, string> = {
  temperature: "°C",
  pressure: "Pa",
  volume: "m³",
  mass_flow_rate: "kg/s",
  t_res_s: "s",
  dt: "s",
  end_time: "s",
  max_time: "s",
  electric_power_kW: "kW",
  // Generic geometric / electrical / timing keys (SI storage).
  radius: "m",
  initial_radius: "m",
  gap: "m",
  length: "m",
  gas_temperature: "K",
  electron_temperature: "K",
  ambient_temperature: "K",
  electrode_temperature: "K",
  ambient_pressure: "Pa",
  external_pressure: "Pa",
  electron_density: "m⁻³",
  voltage: "V",
  off_voltage: "V",
  internal_resistance: "Ω",
  impedance: "Ω",
  wire_resistance: "Ω",
  wire_inductance: "H",
  initial_current: "A",
  wave_speed: "m/s",
  pulse_energy: "J",
  rise_time: "s",
  on_time: "s",
  fall_time: "s",
  t_start: "s",
  t_end: "s",
  output_interval: "s",
  tau_transition: "s",
};

/**
 * Format a label with its unit, e.g. "pressure [Pa]".
 * When `unit` is supplied it is used directly; otherwise the unit is looked up
 * from PROPERTY_DISPLAY_UNIT by key name. Keys with no known unit are returned
 * unchanged.
 */
export function labelWithUnit(label: string, unit?: string): string {
  const u = unit ?? PROPERTY_DISPLAY_UNIT[label];
  return u ? `${label} [${u}]` : label;
}

/**
 * Convert Pascal to bar.
 */
export function pascalToBar(pascal: number): number {
  return pascal / 100000;
}

/**
 * Convert bar to Pascal.
 */
export function barToPascal(bar: number): number {
  return bar * 100000;
}

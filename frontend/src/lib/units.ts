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
 */
export function formatNumber(value: number, decimals: number = 2): string {
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

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
 * Format a label with its unit, e.g. "Temperature (K)" or "Pressure (Pa)".
 */
export function labelWithUnit(label: string, unit?: string): string {
  return unit ? `${label} (${unit})` : label;
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

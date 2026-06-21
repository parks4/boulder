/** Helpers for consistent Plotly axis configuration in result tabs. */

export function coerceNumericSeries(
  values: Array<number | string> | undefined,
): number[] {
  if (!values?.length) return [];
  return values.map((v) => Number(v)).filter((v) => Number.isFinite(v));
}

export function pressureYAxis(gridcolor: string) {
  return {
    title: { text: "Pressure (Pa)", font: { size: 12 } },
    gridcolor,
    rangemode: "tozero" as const,
    tickformat: ",.0f",
    exponentformat: "none" as const,
  };
}

/**
 * Species trace colors for the composition plots (PlotsTab).
 *
 * Boulder has no built-in notion of which color belongs to which species --
 * a host plugin may register a palette (``plugins.sankey_link_colors``,
 * fetched via ``useSpeciesColors``) which is also what colors the Sankey
 * diagram's species bands, so the two views agree. Species outside that
 * palette fall back to the theme colorway, cycled by legend order.
 */

type Theme = "light" | "dark";

const LIGHT_COLORWAY = [
  "#1f77b4",
  "#ff7f0e",
  "#2ca02c",
  "#d62728",
  "#9467bd",
  "#8c564b",
  "#e377c2",
  "#7f7f7f",
  "#bcbd22",
  "#17becf",
];

const DARK_COLORWAY = [
  "#4A90E2",
  "#7ED321",
  "#F5A623",
  "#D0021B",
  "#9013FE",
  "#50E3C2",
  "#BD10E0",
  "#B8E986",
  "#FF6B6B",
  "#4ECDC4",
];

export function getSpeciesColor(
  species: string,
  theme: Theme,
  fallbackIndex: number,
  overrides: Record<string, string> = {},
): string {
  const override = overrides[species];
  if (override) return override;
  const colorway = theme === "dark" ? DARK_COLORWAY : LIGHT_COLORWAY;
  return colorway[fallbackIndex % colorway.length];
}

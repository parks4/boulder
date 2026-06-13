/** Cytoscape node fill scale (matches ``boulder/styles.py`` and ``ReactorGraph``). */
export const CYTOSCAPE_TEMP_MIN_K = 300;
export const CYTOSCAPE_TEMP_MAX_K = 2273;

type Theme = "light" | "dark";

const NODE_COLORS: Record<Theme, { low: string; high: string }> = {
  light: { low: "#00bfff", high: "#ff6347" },
  dark: { low: "#4A90E2", high: "#E94B3C" },
};

function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace("#", "");
  const n = parseInt(h, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function rgbToHex(r: number, g: number, b: number): string {
  return `#${[r, g, b]
    .map((c) => Math.round(c).toString(16).padStart(2, "0"))
    .join("")}`;
}

function lerpHex(a: string, b: string, t: number): string {
  const ta = hexToRgb(a);
  const tb = hexToRgb(b);
  const u = Math.max(0, Math.min(1, t));
  return rgbToHex(
    ta[0] + (tb[0] - ta[0]) * u,
    ta[1] + (tb[1] - ta[1]) * u,
    ta[2] + (tb[2] - ta[2]) * u,
  );
}

/** Match Cytoscape ``mapData(temperature, 300, 2273, low, high)`` node fill. */
export function temperatureToNodeColor(tempK: number, theme: Theme): string {
  const { low, high } = NODE_COLORS[theme];
  const span = CYTOSCAPE_TEMP_MAX_K - CYTOSCAPE_TEMP_MIN_K;
  const t = (tempK - CYTOSCAPE_TEMP_MIN_K) / span;
  return lerpHex(low, high, t);
}

interface ReactorReport {
  T?: number;
}

interface UpdatedNode {
  id: string;
  properties?: Record<string, unknown>;
}

/** Resolve post-solve temperature [K] for a reactor id, else cold-end default. */
export function resolveNodeTemperatureK(
  nodeId: string,
  reactorReports?: Record<string, unknown>,
  updatedNodes?: UpdatedNode[] | null,
): number {
  const report = reactorReports?.[nodeId] as ReactorReport | undefined;
  if (typeof report?.T === "number") return report.T;

  const updated = updatedNodes?.find((n) => n.id === nodeId);
  const propT = updated?.properties?.temperature;
  if (typeof propT === "number") return propT;

  return CYTOSCAPE_TEMP_MIN_K;
}

/** One Plotly Sankey node color per label, aligned with the Cytoscape graph. */
export function mapSankeyNodeColors(
  nodeLabels: string[],
  reactorReports: Record<string, unknown> | undefined,
  updatedNodes: UpdatedNode[] | null | undefined,
  theme: Theme,
): string[] {
  return nodeLabels.map((label) =>
    temperatureToNodeColor(
      resolveNodeTemperatureK(label, reactorReports, updatedNodes),
      theme,
    ),
  );
}

import { useMemo, useState } from "react";
import Plot from "react-plotly.js";
import { useThemeStore } from "@/stores/themeStore";
import type { ScenarioMeta } from "@/api/scenarios";

// TODO: overlay experimental/reference data points on this chart (planned future enhancement).

interface Props {
  scenarios: ScenarioMeta[];
}

interface YGroup {
  id: string;
  label: string;
  /** Attr keys plotted together as separate traces under this Y choice. */
  keys: { key: string; traceName: string }[];
}

/** A single addable Y-axis series, e.g. one species' mole fraction. */
interface SeriesOption {
  key: string;
  label: string;
}

/** A "quick add" shortcut that adds every key of a multi-species group at once. */
interface SeriesFamily {
  id: string;
  label: string;
  keys: string[];
}

/** Bookkeeping attrs every scenario carries that are never plot axis candidates. */
const NON_AXIS_KEYS = new Set(["order", "computed_at", "schema_version"]);

const FRIENDLY_LABELS: Record<string, string> = {
  t0_K: "Temperature (K)",
  final_temperature_K: "Final temperature (K)",
};

function friendlyLabel(key: string): string {
  if (FRIENDLY_LABELS[key]) return FRIENDLY_LABELS[key];
  return key
    .replace(/^final_/, "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Numeric attr keys present on at least one scenario, excluding bookkeeping fields. */
function numericKeys(scenarios: ScenarioMeta[]): string[] {
  const keys = new Set<string>();
  for (const s of scenarios) {
    for (const [key, value] of Object.entries(s)) {
      if (typeof value === "number" && !NON_AXIS_KEYS.has(key)) keys.add(key);
    }
  }
  return Array.from(keys).sort();
}

/** Group numeric keys (minus the chosen X key) into Y-axis choices: species sharing
 * a "final_X_"/"final_Y_" prefix are grouped as one Mole/Mass Fractions choice with
 * one trace per species; everything else is its own single-trace choice. */
function buildYGroups(keys: string[], xKey: string): YGroup[] {
  const moleSpecies: { key: string; traceName: string }[] = [];
  const massSpecies: { key: string; traceName: string }[] = [];
  const singles: YGroup[] = [];

  for (const key of keys) {
    if (key === xKey) continue;
    const mole = key.match(/^final_X_(.+)$/);
    const mass = key.match(/^final_Y_(.+)$/);
    if (mole) {
      moleSpecies.push({ key, traceName: mole[1] });
    } else if (mass) {
      massSpecies.push({ key, traceName: mass[1] });
    } else {
      singles.push({ id: key, label: friendlyLabel(key), keys: [{ key, traceName: friendlyLabel(key) }] });
    }
  }

  const groups: YGroup[] = [];
  if (moleSpecies.length > 0) {
    groups.push({ id: "mole_fractions", label: "Mole Fractions", keys: moleSpecies });
  }
  if (massSpecies.length > 0) {
    groups.push({ id: "mass_fractions", label: "Mass Fractions", keys: massSpecies });
  }
  groups.push(...singles);
  return groups;
}

/** Flatten Y groups into individually-selectable series plus "add whole family"
 * shortcuts for any group (e.g. Mole Fractions) that bundles more than one
 * species, so a user can either build up a custom combination of species one
 * at a time or add a whole family in one click. */
function buildSeriesOptions(groups: YGroup[]): {
  options: SeriesOption[];
  families: SeriesFamily[];
  labelByKey: Map<string, string>;
  groupLabelByKey: Map<string, string>;
} {
  const options: SeriesOption[] = [];
  const families: SeriesFamily[] = [];
  const labelByKey = new Map<string, string>();
  const groupLabelByKey = new Map<string, string>();

  for (const group of groups) {
    if (group.keys.length > 1) {
      families.push({ id: group.id, label: `${group.label} (all)`, keys: group.keys.map((k) => k.key) });
    }
    for (const { key, traceName } of group.keys) {
      options.push({ key, label: traceName });
      labelByKey.set(key, traceName);
      groupLabelByKey.set(key, group.label);
    }
  }

  return { options, families, labelByKey, groupLabelByKey };
}

/**
 * Sweep-results chart: pick an X axis (the swept parameter, e.g. temperature)
 * and a Y axis (a KPI or KPI family, e.g. mole fractions) and plot every
 * scenario in the active store — the parameter-sweep equivalent of upstream
 * Cantera examples' "species vs. temperature" plots (e.g.
 * continuous_reactor.py). Lives below the Scenarios list in the Scenario
 * (sweep) pane, not the main Plots tab: a sweep produces one point per run,
 * not a single reactor's time/space trajectory.
 *
 * Renders nothing when the store has fewer than two numeric attrs to plot
 * against each other (e.g. a plain multi-case store with no sweep KPIs).
 */
export function SweepResultsPlot({ scenarios }: Props) {
  const theme = useThemeStore((s) => s.theme);

  const keys = useMemo(() => numericKeys(scenarios), [scenarios]);
  const [xKey, setXKey] = useState<string | null>(null);
  /** Individually-selected Y-axis series keys. `null` means the user hasn't
   * touched the picker yet, so a sensible default (the first family, or the
   * first available series) is used instead. */
  const [activeKeys, setActiveKeys] = useState<string[] | null>(null);

  const effectiveXKey = xKey && keys.includes(xKey) ? xKey : (keys.includes("t0_K") ? "t0_K" : keys[0]);
  const yGroups = useMemo(
    () => (effectiveXKey ? buildYGroups(keys, effectiveXKey) : []),
    [keys, effectiveXKey],
  );
  const { options, families, labelByKey, groupLabelByKey } = useMemo(
    () => buildSeriesOptions(yGroups),
    [yGroups],
  );

  const validKeys = useMemo(() => new Set(options.map((o) => o.key)), [options]);
  const effectiveActiveKeys = useMemo(() => {
    if (activeKeys !== null) return activeKeys.filter((k) => validKeys.has(k));
    if (families.length > 0) return families[0].keys;
    if (options.length > 0) return [options[0].key];
    return [];
  }, [activeKeys, validKeys, families, options]);

  const addKey = (key: string) => {
    if (effectiveActiveKeys.includes(key)) return;
    setActiveKeys([...effectiveActiveKeys, key]);
  };
  const addFamily = (familyId: string) => {
    const family = families.find((f) => f.id === familyId);
    if (!family) return;
    const merged = [...effectiveActiveKeys];
    for (const key of family.keys) {
      if (!merged.includes(key)) merged.push(key);
    }
    setActiveKeys(merged);
  };
  const removeKey = (key: string) => {
    setActiveKeys(effectiveActiveKeys.filter((k) => k !== key));
  };

  const availableFamilies = families.filter(
    (f) => !f.keys.every((k) => effectiveActiveKeys.includes(k)),
  );
  const availableOptions = options.filter((o) => !effectiveActiveKeys.includes(o.key));

  const yAxisTitle = (() => {
    const labels = new Set(effectiveActiveKeys.map((k) => groupLabelByKey.get(k) ?? k));
    return labels.size === 1 ? [...labels][0] : "Value";
  })();

  const { xValues, series } = useMemo(() => {
    if (!effectiveXKey) return { xValues: [], series: [] };
    const withX = scenarios.filter((s) => typeof s[effectiveXKey] === "number");
    const sorted = [...withX].sort(
      (a, b) => (a[effectiveXKey] as number) - (b[effectiveXKey] as number),
    );
    const x = sorted.map((s) => s[effectiveXKey] as number);
    const traces = effectiveActiveKeys.map((key) => ({
      name: labelByKey.get(key) ?? key,
      y: sorted.map((s) => (s[key] as number | undefined) ?? null),
    }));
    return { xValues: x, series: traces };
  }, [scenarios, effectiveXKey, effectiveActiveKeys, labelByKey]);

  if (keys.length < 2 || !effectiveXKey || options.length === 0 || xValues.length === 0) {
    return null;
  }

  const selectClass =
    "rounded-md border border-border bg-background px-2 py-1 text-xs text-foreground";

  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-2">
      <h3 className="font-semibold text-sm text-foreground">Sweep results</h3>
      <div className="flex flex-col gap-1.5">
        <label className="flex items-center gap-1.5 text-[10px] text-muted-foreground">
          X axis
          <select
            className={`${selectClass} flex-1`}
            value={effectiveXKey}
            onChange={(e) => setXKey(e.target.value)}
          >
            {keys.map((k) => (
              <option key={k} value={k}>
                {friendlyLabel(k)}
              </option>
            ))}
          </select>
        </label>
        <div className="flex flex-col gap-1 text-[10px] text-muted-foreground">
          <div className="flex items-center gap-1.5">
            <span className="shrink-0">Y axis</span>
            <select
              className={`${selectClass} flex-1`}
              value=""
              disabled={availableFamilies.length === 0 && availableOptions.length === 0}
              data-testid="y-axis-add-select"
              onChange={(e) => {
                const value = e.target.value;
                if (!value) return;
                if (value.startsWith("f:")) addFamily(value.slice(2));
                else if (value.startsWith("k:")) addKey(value.slice(2));
              }}
            >
              <option value="">+ Add series…</option>
              {availableFamilies.length > 0 && (
                <optgroup label="Quick add">
                  {availableFamilies.map((f) => (
                    <option key={f.id} value={`f:${f.id}`}>
                      {f.label}
                    </option>
                  ))}
                </optgroup>
              )}
              {availableOptions.length > 0 && (
                <optgroup label="Individual series">
                  {availableOptions.map((o) => (
                    <option key={o.key} value={`k:${o.key}`}>
                      {o.label}
                    </option>
                  ))}
                </optgroup>
              )}
            </select>
          </div>
          {effectiveActiveKeys.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {effectiveActiveKeys.map((key) => {
                const label = labelByKey.get(key) ?? key;
                return (
                  <span
                    key={key}
                    data-testid={`active-series-chip-${key}`}
                    className="inline-flex items-center gap-1 rounded-full border border-border bg-muted px-2 py-0.5 text-[10px] text-foreground"
                  >
                    {label}
                    <button
                      type="button"
                      onClick={() => removeKey(key)}
                      aria-label={`Remove ${label}`}
                      data-testid={`remove-series-${key}`}
                      className="leading-none text-muted-foreground hover:text-foreground"
                    >
                      ×
                    </button>
                  </span>
                );
              })}
            </div>
          )}
        </div>
      </div>
      <Plot
        data={series.map((s) => ({
          x: xValues,
          y: s.y,
          type: "scatter" as const,
          mode: "lines+markers" as const,
          name: s.name,
        }))}
        layout={{
          paper_bgcolor: "transparent",
          plot_bgcolor: "transparent",
          font: { color: theme === "dark" ? "#ccc" : "#333", size: 11 },
          margin: { t: 10, b: 40, l: 50, r: 10 },
          height: 220,
          showlegend: true,
          legend: { x: 1, xanchor: "right" as const, y: 1 },
          xaxis: {
            title: { text: friendlyLabel(effectiveXKey) },
            gridcolor: theme === "dark" ? "#333" : "#e0e0e0",
          },
          yaxis: {
            title: { text: yAxisTitle },
            gridcolor: theme === "dark" ? "#333" : "#e0e0e0",
          },
        }}
        config={{ displaylogo: false, responsive: true }}
        style={{ width: "100%" }}
        useResizeHandler
      />
    </div>
  );
}

import { useState, useEffect, useRef } from "react";
import { useSelectionStore } from "@/stores/selectionStore";
import { useConfigStore } from "@/stores/configStore";
import { useScenarioStore } from "@/stores/scenarioStore";
import { useSimulationStore } from "@/stores/simulationStore";
import { useSweepRunStore } from "@/stores/sweepStore";
import { BASELINE_SCENARIO_ID, updateScenarioEntity } from "@/api/scenarios";
import type { NormalizedConfig } from "@/types/config";
import { kelvinToCelsius, celsiusToKelvin, formatNumber, labelWithUnit } from "@/lib/units";
import { useKindSchema } from "@/hooks/useKindSchema";
import { useKinds } from "@/hooks/useKinds";
import { Button } from "@/components/ui/Button";
import { Tooltip } from "@/components/ui/Tooltip";
import { ConfirmDeleteNodeModal } from "@/components/modals/ConfirmDeleteNodeModal";
import { StageCard } from "@/components/panels/StageCard";
import { toast } from "sonner";

/** The config's one stage, when it has exactly one — undefined for 0 or 2+. */
function getSoleGroup(config: NormalizedConfig): string | undefined {
  const groups = new Set(
    [...config.nodes.map((n) => n.group), ...config.connections.map((c) => c.group)].filter(
      (g): g is string => typeof g === "string" && g.length > 0,
    ),
  );
  return groups.size === 1 ? [...groups][0] : undefined;
}

// Display-order keys that should always render last, regardless of where
// they land in the underlying properties dict (e.g. `plot_options` is
// metadata about *how* to chart the node, not a physical initial condition).
const _TRAILING_DISPLAY_KEYS = ["plot_options"];

function unfoldInitialConditions(
  properties: Record<string, unknown>,
): Record<string, unknown> {
  const flat = { ...properties };
  const initial = flat.initial;
  if (initial && typeof initial === "object" && !Array.isArray(initial)) {
    delete flat.initial;
    for (const [key, value] of Object.entries(initial as Record<string, unknown>)) {
      if (!(key in flat)) {
        flat[key] = value;
      }
    }
  }
  // Underscore-prefixed keys are private/internal by convention (mirrors
  // Python's own convention) -- a plugin annotation for other tooling (e.g.
  // display styling), not a physical input the user should see or edit.
  for (const key of Object.keys(flat)) {
    if (key.startsWith("_")) {
      delete flat[key];
    }
  }
  // Re-insert trailing keys last -- deleting and re-adding moves a key to the
  // end of a plain object's insertion-order iteration.
  for (const key of _TRAILING_DISPLAY_KEYS) {
    if (key in flat) {
      const value = flat[key];
      delete flat[key];
      flat[key] = value;
    }
  }
  return flat;
}

/** Render a property value the same way for the display span and override tooltips. */
function formatDisplayValue(key: string, value: unknown): string {
  if (key === "temperature" && typeof value === "number") {
    return `${kelvinToCelsius(value).toFixed(2)} °C`;
  }
  if (typeof value === "number") return formatNumber(value);
  if (typeof value === "object" && value !== null) return JSON.stringify(value);
  return String(value ?? "");
}

function buildEditValuesFromProperties(
  displayProperties: Record<string, unknown>,
): Record<string, string> {
  const vals: Record<string, string> = {};
  for (const [key, value] of Object.entries(displayProperties)) {
    if (key === "temperature" && typeof value === "number") {
      vals[key] = String(kelvinToCelsius(value).toFixed(2));
    } else if (typeof value === "object" && value !== null) {
      // Object-valued properties (e.g. a node's `plot: {hide_species, show_species}`
      // hints) must be JSON-stringified same as the display-mode span below --
      // plain `String(value)` on an object yields the useless "[object Object]".
      vals[key] = JSON.stringify(value);
    } else {
      vals[key] = String(value ?? "");
    }
  }
  return vals;
}

export function PropertiesPanel() {
  const selectedElement = useSelectionStore((s) => s.selectedElement);
  const initialConditionsEditNonce = useSelectionStore((s) => s.initialConditionsEditNonce);
  const config = useConfigStore((s) => s.config);
  const updateNode = useConfigStore((s) => s.updateNode);
  const updateConnection = useConfigStore((s) => s.updateConnection);
  const removeNode = useConfigStore((s) => s.removeNode);
  const removeConnection = useConfigStore((s) => s.removeConnection);
  const clearSelection = useSelectionStore((s) => s.clearSelection);
  const previewId = useScenarioStore((s) => s.previewId);
  const previewNodes = useScenarioStore((s) => s.previewNodes);
  const previewConnections = useScenarioStore((s) => s.previewConnections);
  const activeScenarioId = useScenarioStore((s) => s.activeId);
  const scenarioOverlays = useScenarioStore((s) => s.overlays);
  const applyScenarioOverlays = useScenarioStore((s) => s.applyOverlays);
  const loadScenarioPreview = useScenarioStore((s) => s.loadPreview);
  const isSimulating = useSimulationStore((s) => s.isRunning);
  const isSweeping = useSweepRunStore((s) => s.sweeping);
  const [isEditing, setIsEditing] = useState(false);
  const [editValues, setEditValues] = useState<Record<string, string>>({});
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const handledEditNonceRef = useRef(0);
  const prevSelectedElementRef = useRef<typeof selectedElement>(null);

  // Double-click on a graph node bumps initialConditionsEditNonce.
  useEffect(() => {
    const element = selectedElement;
    if (!element) {
      setIsEditing(false);
      prevSelectedElementRef.current = null;
      return;
    }

    const elementChanged = prevSelectedElementRef.current !== element;
    prevSelectedElementRef.current = element;

    if (initialConditionsEditNonce > handledEditNonceRef.current) {
      handledEditNonceRef.current = initialConditionsEditNonce;

      if (element.data.isGroup) {
        setIsEditing(false);
        return;
      }

      const isNode = element.type === "node";
      const id = String(element.data.id);
      const entity = isNode
        ? config.nodes.find((n) => n.id === id)
        : config.connections.find((c) => c.id === id);
      if (!entity) {
        setIsEditing(false);
        return;
      }

      const properties = entity.properties as Record<string, unknown>;
      const isStreamPoint = isNode && Boolean(properties.stream_point);
      const isTerminalSink = isNode && Boolean(properties.terminal_sink);
      if (isStreamPoint || isTerminalSink) {
        setIsEditing(false);
        return;
      }

      const displayProperties = unfoldInitialConditions(properties);
      setEditValues(buildEditValuesFromProperties(displayProperties));
      setIsEditing(true);
      return;
    }

    if (elementChanged) {
      setIsEditing(false);
    }
  }, [selectedElement, initialConditionsEditNonce, config]);

  // The kind of the selected element. A selection made from the graph carries
  // `type` in its cytoscape data, but a programmatic one need not — selecting
  // a scenario auto-selects a reactor by id alone (see scenarioStore's
  // setActive). The config entry always has the kind, so fall back to it;
  // otherwise both the heading below and the schema lookup here come up empty
  // whenever a scenario is being previewed.
  const selectedConfigEntity =
    selectedElement && !selectedElement.data.isGroup
      ? (selectedElement.type === "node"
          ? config.nodes.find((n) => n.id === String(selectedElement.data.id))
          : config.connections.find((c) => c.id === String(selectedElement.data.id)))
      : undefined;

  // Field metadata from the kind's registered schema (descriptions, enum
  // options, conditional visibility). Fetched before any early return so
  // the hook order stays stable.
  const schemaKind =
    selectedElement && !selectedElement.data.isGroup
      ? String(selectedElement.data.type ?? selectedConfigEntity?.type ?? "")
      : "";
  const schemaMeta = useKindSchema(schemaKind);
  const { reactors, connections } = useKinds();

  if (!selectedElement) {
    // A config with exactly one stage has no clickable stage box (see
    // ReactorGraph's suppressDefaultGroup) — show that stage's panel by
    // default instead, so its solver controls are still reachable.
    const soleGroup = getSoleGroup(config);
    if (soleGroup) {
      return <StageCard stageId={soleGroup} />;
    }
    return (
      <div id="properties-panel" className="rounded-lg border border-border bg-card p-4">
        <p className="text-xs text-muted-foreground italic">
          Click a node or edge in the graph to view its properties.
        </p>
      </div>
    );
  }

  const isNode = selectedElement.type === "node";
  const id = String(selectedElement.data.id);
  const entityType = schemaKind;
  const kindDoc = (isNode ? reactors : connections).find((k) => k.kind === entityType);

  // Group compound box (a stage) selected — show the Stage panel instead.
  if (selectedElement.data.isGroup) {
    return <StageCard stageId={id} />;
  }

  // Get full properties from config store (graph data may be subset)
  const entity = isNode
    ? config.nodes.find((n) => n.id === id)
    : config.connections.find((c) => c.id === id);

  const properties = entity ? (entity.properties as Record<string, unknown>) : {};
  const displayProperties = unfoldInitialConditions(properties);

  // A selected scenario's effective (base + overlay) properties for this same
  // element — lets the Inputs pane preview a scenario's overrides (e.g. a
  // reactor's length) the moment it's selected, even before Run Sweep has
  // solved it. Falls back to the base properties when nothing is previewed,
  // when this element has no counterpart in the preview (shouldn't happen in
  // practice — the preview mirrors the whole network — but is not fatal), or
  // when BASELINE is active: BASELINE has no overlay of its own, so its
  // "preview" is always identical to the live base config -- going through
  // the (server-computed, fetch-once) preview instead of the live base
  // properties would show a stale value after editing the base network
  // while BASELINE happens to be the active selection.
  const previewList = isNode ? previewNodes : previewConnections;
  const previewEntity =
    previewId && previewId !== BASELINE_SCENARIO_ID
      ? previewList?.find((e) => e.id === id)
      : undefined;
  const previewDisplayProperties = previewEntity
    ? unfoldInitialConditions(previewEntity.properties as Record<string, unknown>)
    : displayProperties;
  // What's shown, editing or not, is always the *currently effective* value
  // (base, or the active scenario's override if there is one) -- Save now
  // folds into that same scenario's overlay (see handleSave), so editing the
  // base value while a 0.20 override is in effect would silently show the
  // wrong starting point.
  const renderProperties = previewDisplayProperties;

  // Stream-point nodes (inter-stage diamonds) and legacy terminal OutletSink nodes
  // are computed from upstream reactors.  OutletSink + terminal_sink is deprecated;
  // remove isTerminalSink when OutletSink is dropped from STONE.
  const isStreamPoint = isNode && Boolean(properties.stream_point);
  const isTerminalSink = isNode && Boolean(properties.terminal_sink);
  const isComputedStream = isStreamPoint || isTerminalSink;

  // A field with visible_when metadata is shown only while every referenced
  // sibling holds the required value (e.g. nb_reflections only for the
  // "series" reflection model). Evaluated against the live edit values while
  // editing so toggling the controlling field reveals its dependents.
  const isFieldVisible = (key: string): boolean => {
    const cond = schemaMeta?.[key]?.visibleWhen;
    if (!cond) return true;
    return Object.entries(cond).every(([dep, expected]) => {
      const current = isEditing ? editValues[dep] : renderProperties[dep];
      return String(current ?? "") === String(expected);
    });
  };

  // Tooltip text: the schema description, plus the enum options if any.
  const fieldTooltip = (key: string): string | undefined => {
    const meta = schemaMeta?.[key];
    if (!meta) return undefined;
    const parts: string[] = [];
    if (meta.description) parts.push(meta.description);
    if (meta.options) parts.push(`Options: ${meta.options.join(" | ")}`);
    return parts.length ? parts.join("\n") : undefined;
  };

  // Start editing
  const handleEdit = () => {
    setEditValues(buildEditValuesFromProperties(previewDisplayProperties));
    setIsEditing(true);
  };

  // Save edits
  const handleSave = () => {
    const updated: Record<string, unknown> = {};
    for (const [key, val] of Object.entries(editValues)) {
      const original = previewDisplayProperties[key];
      if (key === "temperature") {
        updated[key] = celsiusToKelvin(parseFloat(val) || 0);
      } else if (typeof original === "object" && original !== null) {
        // Object-valued properties round-trip through JSON text in the edit
        // box (see buildEditValuesFromProperties) -- parse back to an object
        // rather than saving the raw JSON string over the original value.
        try {
          updated[key] = JSON.parse(val);
        } catch {
          updated[key] = original;
        }
      } else {
        const num = parseFloat(val);
        updated[key] = isNaN(num) ? val : num;
      }
    }

    // A real scenario (not BASELINE, which has no overlay of its own) is
    // active: land the edit in its overlay instead of the base network --
    // otherwise "Save" would silently change the base for every scenario.
    // Only send keys that actually changed, so untouched fields that merely
    // round-tripped through the edit form don't get duplicated into the
    // overlay.
    if (activeScenarioId && activeScenarioId !== BASELINE_SCENARIO_ID) {
      // A running sweep already captured its own snapshot of every overlay
      // when it started, so editing mid-sweep can't race it -- but the
      // sweep's in-flight results still reflect the *old* values, which
      // would be confusing to edit against. Same guard the YAML panes use.
      if (isSimulating || isSweeping) {
        toast.error("Wait for the current calculation to finish before editing a scenario.");
        return;
      }
      const changed: Record<string, unknown> = {};
      for (const [key, val] of Object.entries(updated)) {
        if (JSON.stringify(val) !== JSON.stringify(previewDisplayProperties[key])) {
          changed[key] = val;
        }
      }
      if (Object.keys(changed).length === 0) {
        // Diffed against what was actually shown/edited (the scenario's
        // current effective value -- base or an existing override, per
        // handleEdit) -- an unmodified Save is a true no-op here, distinct
        // from the case where an override already existed and got typed
        // back to the *base* value (that lands in `changed` above and is
        // sent, redundantly setting the overlay to match base -- harmless,
        // and clears the amber "overridden" styling since the effective
        // value now equals base again). Surfaced explicitly rather than
        // silently doing nothing, which otherwise looks identical to a
        // successful save.
        setIsEditing(false);
        toast.info("No changes to save");
        return;
      }
      updateScenarioEntity(scenarioOverlays, activeScenarioId, id, changed)
        .then(async (resp) => {
          setIsEditing(false);
          // Bumps scenarioStore.revision -- lets a scenario YAML pane left
          // open on this same scenario notice this out-of-band edit and
          // refetch its content instead of showing stale text.
          applyScenarioOverlays(resp.overlays);
          // The write itself can succeed while leaving the scenario's
          // *merged* config invalid (e.g. a cross-node consistency rule) --
          // loadPreview swallows that into previewError rather than
          // rejecting, so it must be checked explicitly or the failure is
          // silent: the edit looks like it didn't "take" with no clue why.
          await loadScenarioPreview(activeScenarioId);
          const previewError = useScenarioStore.getState().previewError;
          if (previewError) {
            toast.error(
              `Scenario "${activeScenarioId}" overlay saved, but it no longer previews cleanly: ${previewError}`,
            );
          } else {
            toast.success(`Scenario "${activeScenarioId}" overlay updated`);
          }
        })
        .catch((err) => {
          toast.error(
            `Could not update scenario overlay: ${err instanceof Error ? err.message : String(err)}`,
          );
        });
      return;
    }

    if (isNode) {
      updateNode(id, { properties: { ...properties, ...updated } });
    } else {
      updateConnection(id, { properties: { ...properties, ...updated } });
    }
    setIsEditing(false);
    toast.success("Properties saved");
  };

  const handleDeleteClick = () => {
    if (isNode) {
      setShowDeleteConfirm(true);
      return;
    }
    removeConnection(id);
    clearSelection();
    toast.info(`Deleted ${id}`);
  };

  const handleConfirmDeleteNode = () => {
    removeNode(id);
    clearSelection();
    setShowDeleteConfirm(false);
    toast.info(`Deleted ${id}`);
  };

  return (
    <div id="properties-panel" className="rounded-lg border border-border bg-card p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="font-semibold text-sm text-foreground">{id}</h3>
          <div className="flex items-center gap-1">
            <span className="text-xs text-muted-foreground">{entityType}</span>
            {kindDoc?.doc_url && (
              <Tooltip
                content={
                  <span className="block space-y-1">
                    {kindDoc.description && (
                      <span className="block">{kindDoc.description}</span>
                    )}
                    <a
                      href={kindDoc.doc_url}
                      target="_blank"
                      rel="noreferrer"
                      className="underline text-primary"
                    >
                      Docs
                    </a>
                  </span>
                }
              >
                <span
                  className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[10px] text-muted-foreground cursor-help"
                  aria-label={`About ${entityType}`}
                >
                  ⓘ
                </span>
              </Tooltip>
            )}
          </div>
        </div>
        {!isComputedStream && (
          <div className="flex gap-1">
            {!isEditing ? (
              <Button onClick={handleEdit} variant="secondary" size="sm" className="text-xs">
                Edit
              </Button>
            ) : (
              <Button onClick={handleSave} variant="primary" size="sm" className="text-xs">
                Save
              </Button>
            )}
            <Button
              id="delete-element"
              onClick={handleDeleteClick}
              variant="destructive"
              size="sm"
              className="text-xs"
            >
              Delete
            </Button>
          </div>
        )}
      </div>

      {!isComputedStream && (
        <div className="border-t border-border pt-2 mt-1">
          <p className="text-xs text-muted-foreground mb-1.5">Initial conditions</p>
          <div className="divide-y divide-border">
            {Object.entries(renderProperties)
              .filter(([key]) => isFieldVisible(key))
              .map(([key, value]) => {
            // Only meaningful outside edit mode — editing always shows the
            // base config's own value (renderProperties === displayProperties then).
            const isOverridden =
              !isEditing &&
              Boolean(previewEntity) &&
              JSON.stringify(value) !== JSON.stringify(displayProperties[key]);
            return (
            <div key={key} className="py-1.5 flex items-center justify-between gap-2">
              <span
                className={`text-xs text-muted-foreground truncate ${
                  fieldTooltip(key) ? "cursor-help underline decoration-dotted" : ""
                }`}
                title={fieldTooltip(key)}
              >
                {labelWithUnit(key)}
              </span>
              {isEditing ? (
                schemaMeta?.[key]?.options ? (
                  <select
                    value={editValues[key] ?? ""}
                    onChange={(e) =>
                      setEditValues((prev) => ({ ...prev, [key]: e.target.value }))
                    }
                    className="w-28 text-xs px-1.5 py-1 rounded bg-input border border-border text-foreground"
                  >
                    {schemaMeta[key].options!.map((opt) => (
                      <option key={opt} value={opt}>
                        {opt}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    value={editValues[key] ?? ""}
                    onChange={(e) =>
                      setEditValues((prev) => ({ ...prev, [key]: e.target.value }))
                    }
                    className="w-28 text-xs px-1.5 py-1 rounded bg-input border border-border text-foreground"
                  />
                )
              ) : (
                <span
                  className={`text-xs font-mono ${
                    isOverridden
                      ? "text-amber-600 dark:text-amber-400 font-semibold"
                      : "text-foreground"
                  }`}
                  title={
                    isOverridden
                      ? `Baseline value: ${formatDisplayValue(key, displayProperties[key])}`
                      : undefined
                  }
                >
                  {formatDisplayValue(key, value)}
                </span>
              )}
            </div>
            );
          })}
          {Object.keys(renderProperties).length === 0 && (
            <p className="text-xs text-muted-foreground py-1 italic">No properties</p>
          )}
          </div>
        </div>
      )}

      {isComputedStream && (
        <div className="border-t border-border pt-2 mt-1">
          <p className="text-xs font-medium text-foreground mb-1.5">
            Material Stream
          </p>
          <div className="divide-y divide-border text-xs">
            {properties.source_node != null && (
              <div className="py-1 flex justify-between gap-2">
                <span className="text-muted-foreground">Source</span>
                <span className="font-mono">{String(properties.source_node)}</span>
              </div>
            )}
            {Array.isArray(properties.target_nodes) && properties.target_nodes.length > 0 && (
              <div className="py-1 flex justify-between gap-2">
                <span className="text-muted-foreground">Target(s)</span>
                <span className="font-mono">
                  {(properties.target_nodes as unknown[]).map(String).join(", ")}
                </span>
              </div>
            )}
            {typeof properties.temperature === "number" && (
              <div className="py-1 flex justify-between gap-2">
                <span className="text-muted-foreground">T</span>
                <span className="font-mono">
                  {kelvinToCelsius(properties.temperature).toFixed(1)} °C
                </span>
              </div>
            )}
            {typeof properties.pressure === "number" && (
              <div className="py-1 flex justify-between gap-2">
                <span className="text-muted-foreground">P</span>
                <span className="font-mono">
                  {(properties.pressure / 1e5).toFixed(3)} bar
                </span>
              </div>
            )}
            {typeof properties.mdot === "number" && (
              <div className="py-1 flex justify-between gap-2">
                <span className="text-muted-foreground">ṁ</span>
                <span className="font-mono">
                  {formatNumber(properties.mdot, 4)} kg/s
                </span>
              </div>
            )}
            {typeof properties.h_mass === "number" && properties.h_mass !== 0 && (
              <div className="py-1 flex justify-between gap-2">
                <span className="text-muted-foreground">h</span>
                <span className="font-mono">
                  {formatNumber(properties.h_mass / 1e3)} kJ/kg
                </span>
              </div>
            )}
            {typeof properties.density === "number" && properties.density !== 0 && (
              <div className="py-1 flex justify-between gap-2">
                <span className="text-muted-foreground">ρ</span>
                <span className="font-mono">
                  {formatNumber(properties.density)} kg/m³
                </span>
              </div>
            )}
            {typeof properties.v_dot_normal_m3_h === "number" &&
              properties.v_dot_normal_m3_h !== 0 && (
              <div className="py-1 flex justify-between gap-2">
                <span className="text-muted-foreground">V̇ (normal)</span>
                <span className="font-mono">
                  {formatNumber(properties.v_dot_normal_m3_h)} Nm³/h
                </span>
              </div>
            )}
            {typeof properties.v_dot_real_m3_h === "number" &&
              properties.v_dot_real_m3_h !== 0 && (
              <div className="py-1 flex justify-between gap-2">
                <span className="text-muted-foreground">V̇ (real)</span>
                <span className="font-mono">
                  {formatNumber(properties.v_dot_real_m3_h)} m³/h
                </span>
              </div>
            )}
            {properties.top_Y != null &&
              typeof properties.top_Y === "object" &&
              Object.keys(properties.top_Y).length > 0 && (
              <div className="py-1">
                <span className="text-muted-foreground block mb-0.5">Top species (Y)</span>
                <div className="pl-2 space-y-0.5">
                  {Object.entries(properties.top_Y as Record<string, number>).map(
                    ([sp, y]) => (
                      <div key={sp} className="flex justify-between gap-2">
                        <span className="text-muted-foreground font-mono">{sp}</span>
                        <span className="font-mono">{y.toFixed(4)}</span>
                      </div>
                    )
                  )}
                </div>
              </div>
            )}
            {properties.upstream_stage != null && (
              <div className="py-1 flex justify-between gap-2">
                <span className="text-muted-foreground">From stage</span>
                <span className="font-mono">{String(properties.upstream_stage)}</span>
              </div>
            )}
          </div>
        </div>
      )}

      {!isNode && entity && (
        <div className="text-xs text-muted-foreground">
          <span>Source: {String("source" in entity ? entity.source : "N/A")}</span>
          {" → "}
          <span>Target: {String("target" in entity ? entity.target : "N/A")}</span>
        </div>
      )}

      {isNode && (
        <ConfirmDeleteNodeModal
          open={showDeleteConfirm}
          nodeId={id}
          nodeType={entityType}
          onClose={() => setShowDeleteConfirm(false)}
          onConfirm={handleConfirmDeleteNode}
        />
      )}
    </div>
  );
}

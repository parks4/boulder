import { useState } from "react";
import { useSelectionStore } from "@/stores/selectionStore";
import { useConfigStore } from "@/stores/configStore";
import { kelvinToCelsius, celsiusToKelvin, formatNumber, labelWithUnit } from "@/lib/units";
import { useKindSchema } from "@/hooks/useKindSchema";
import { Button } from "@/components/ui/Button";
import { ConfirmDeleteNodeModal } from "@/components/modals/ConfirmDeleteNodeModal";
import { toast } from "sonner";

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
  return flat;
}

export function PropertiesPanel() {
  const selectedElement = useSelectionStore((s) => s.selectedElement);
  const config = useConfigStore((s) => s.config);
  const updateNode = useConfigStore((s) => s.updateNode);
  const updateConnection = useConfigStore((s) => s.updateConnection);
  const removeNode = useConfigStore((s) => s.removeNode);
  const removeConnection = useConfigStore((s) => s.removeConnection);
  const clearSelection = useSelectionStore((s) => s.clearSelection);
  const [isEditing, setIsEditing] = useState(false);
  const [editValues, setEditValues] = useState<Record<string, string>>({});
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  // Field metadata from the kind's registered schema (descriptions, enum
  // options, conditional visibility). Fetched before any early return so
  // the hook order stays stable.
  const schemaKind =
    selectedElement && !selectedElement.data.isGroup
      ? String(selectedElement.data.type ?? "")
      : "";
  const schemaMeta = useKindSchema(schemaKind);

  if (!selectedElement) {
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
  const entityType = String(selectedElement.data.type ?? "");

  // Group compound box selected — show a minimal summary panel.
  if (selectedElement.data.isGroup) {
    const childNodes = config.nodes.filter((n) => n.group === id);
    return (
      <div id="properties-panel" className="rounded-lg border border-border bg-card p-4 space-y-3">
        <div>
          <h3 className="font-semibold text-sm text-foreground">{id}</h3>
          <span className="text-xs text-muted-foreground">Stage group</span>
        </div>
        <div className="border-t border-border pt-2 mt-1">
          <p className="text-xs text-muted-foreground mb-1.5">Child nodes</p>
          <div className="divide-y divide-border">
            {childNodes.map((n) => (
              <div key={n.id} className="py-1 flex items-center justify-between gap-2">
                <span className="text-xs font-mono text-foreground">{n.id}</span>
                <span className="text-xs text-muted-foreground">{n.type}</span>
              </div>
            ))}
            {childNodes.length === 0 && (
              <p className="text-xs text-muted-foreground py-1 italic">No child nodes</p>
            )}
          </div>
        </div>
      </div>
    );
  }

  // Get full properties from config store (graph data may be subset)
  const entity = isNode
    ? config.nodes.find((n) => n.id === id)
    : config.connections.find((c) => c.id === id);

  const properties = entity ? (entity.properties as Record<string, unknown>) : {};
  const displayProperties = unfoldInitialConditions(properties);

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
      const current = isEditing ? editValues[dep] : properties[dep];
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
    const vals: Record<string, string> = {};
    for (const [key, value] of Object.entries(displayProperties)) {
      if (key === "temperature" && typeof value === "number") {
        vals[key] = String(kelvinToCelsius(value).toFixed(2));
      } else {
        vals[key] = String(value ?? "");
      }
    }
    setEditValues(vals);
    setIsEditing(true);
  };

  // Save edits
  const handleSave = () => {
    const updated: Record<string, unknown> = {};
    for (const [key, val] of Object.entries(editValues)) {
      if (key === "temperature") {
        updated[key] = celsiusToKelvin(parseFloat(val) || 0);
      } else {
        const num = parseFloat(val);
        updated[key] = isNaN(num) ? val : num;
      }
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
          <span className="text-xs text-muted-foreground">{entityType}</span>
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
            {Object.entries(displayProperties)
              .filter(([key]) => isFieldVisible(key))
              .map(([key, value]) => (
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
                <span className="text-xs font-mono text-foreground">
                  {key === "temperature" && typeof value === "number"
                    ? `${kelvinToCelsius(value).toFixed(2)} °C`
                    : typeof value === "number"
                      ? formatNumber(value)
                      : typeof value === "object" && value !== null
                        ? JSON.stringify(value)
                        : String(value ?? "")}
                </span>
              )}
            </div>
          ))}
          {Object.keys(displayProperties).length === 0 && (
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

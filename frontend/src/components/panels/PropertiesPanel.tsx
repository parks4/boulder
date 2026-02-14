import { useState, useCallback } from "react";
import { useSelectionStore } from "@/stores/selectionStore";
import { useConfigStore } from "@/stores/configStore";
import { kelvinToCelsius, celsiusToKelvin, formatNumber, labelWithUnit } from "@/lib/units";
import { Button } from "@/components/ui/Button";
import { toast } from "sonner";

export function PropertiesPanel() {
  const selectedElement = useSelectionStore((s) => s.selectedElement);
  const config = useConfigStore((s) => s.config);
  const updateNode = useConfigStore((s) => s.updateNode);
  const updateConnection = useConfigStore((s) => s.updateConnection);
  const removeNode = useConfigStore((s) => s.removeNode);
  const removeConnection = useConfigStore((s) => s.removeConnection);
  const [isEditing, setIsEditing] = useState(false);
  const [editValues, setEditValues] = useState<Record<string, string>>({});

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

  // Get full properties from config store (graph data may be subset)
  const entity = isNode
    ? config.nodes.find((n) => n.id === id)
    : config.connections.find((c) => c.id === id);

  const properties = entity ? (entity.properties as Record<string, unknown>) : {};

  // Start editing
  const handleEdit = () => {
    const vals: Record<string, string> = {};
    for (const [key, value] of Object.entries(properties)) {
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

  const handleDelete = () => {
    if (isNode) removeNode(id);
    else removeConnection(id);
    toast.info(`Deleted ${id}`);
  };

  return (
    <div id="properties-panel" className="rounded-lg border border-border bg-card p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="font-semibold text-sm text-foreground">{id}</h3>
          <span className="text-xs text-muted-foreground">{entityType}</span>
        </div>
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
          <Button onClick={handleDelete} variant="destructive" size="sm" className="text-xs">
            Delete
          </Button>
        </div>
      </div>

      <div className="divide-y divide-border">
        {Object.entries(properties).map(([key, value]) => (
          <div key={key} className="py-1.5 flex items-center justify-between gap-2">
            <span className="text-xs text-muted-foreground truncate">
              {labelWithUnit(key)}
            </span>
            {isEditing ? (
              <input
                value={editValues[key] ?? ""}
                onChange={(e) =>
                  setEditValues((prev) => ({ ...prev, [key]: e.target.value }))
                }
                className="w-28 text-xs px-1.5 py-1 rounded bg-input border border-border text-foreground"
              />
            ) : (
              <span className="text-xs font-mono text-foreground">
                {key === "temperature" && typeof value === "number"
                  ? `${kelvinToCelsius(value).toFixed(2)} °C`
                  : typeof value === "number"
                    ? formatNumber(value)
                    : String(value ?? "")}
              </span>
            )}
          </div>
        ))}
        {Object.keys(properties).length === 0 && (
          <p className="text-xs text-muted-foreground py-1 italic">No properties</p>
        )}
      </div>

      {!isNode && entity && (
        <div className="text-xs text-muted-foreground">
          <span>Source: {String("source" in entity ? entity.source : "N/A")}</span>
          {" → "}
          <span>Target: {String("target" in entity ? entity.target : "N/A")}</span>
        </div>
      )}
    </div>
  );
}

import { apiFetch } from "./client";
import type { PluginMeta, PluginRenderData } from "@/types/plugin";

export function fetchPlugins() {
  return apiFetch<PluginMeta[]>("/plugins");
}

export function renderPlugin(
  pluginId: string,
  context: {
    simulation_data?: Record<string, unknown> | null;
    selected_element?: Record<string, unknown> | null;
    config?: Record<string, unknown> | null;
    theme?: string;
  },
) {
  return apiFetch<PluginRenderData>(`/plugins/${pluginId}/render`, {
    method: "POST",
    body: JSON.stringify(context),
  });
}

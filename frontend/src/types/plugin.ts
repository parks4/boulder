/** Metadata for a registered output-pane plugin. */
export interface PluginMeta {
  id: string;
  label: string;
  icon?: string | null;
  requires_selection: boolean;
  supported_element_types: string[];
  /** Reactor kinds the plugin applies to (null/absent = any). */
  supported_node_types?: string[] | null;
}

/** A single content descriptor returned by a plugin. */
export interface PluginContentItem {
  type: "image" | "table" | "text" | "html" | "plotly" | "grid" | "error";
  [key: string]: unknown;
}

/** Rendered plugin data returned by the API. */
export interface PluginRenderData {
  available: boolean;
  message?: string;
  data?: PluginContentItem;
}

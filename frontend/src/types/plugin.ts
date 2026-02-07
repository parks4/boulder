/** Metadata for a registered output-pane plugin. */
export interface PluginMeta {
  id: string;
  label: string;
  icon?: string | null;
  requires_selection: boolean;
  supported_element_types: string[];
}

/** Rendered plugin data returned by the API. */
export interface PluginRenderData {
  available: boolean;
  message?: string;
  data?: {
    type: "image" | "table" | "text" | "html";
    [key: string]: unknown;
  };
}

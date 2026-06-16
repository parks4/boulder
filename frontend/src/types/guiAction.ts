export interface GuiActionMeta {
  id: string;
  label: string;
  requires_simulation: boolean;
  /** True when the server considers this action ready to run right now. */
  is_available: boolean;
}

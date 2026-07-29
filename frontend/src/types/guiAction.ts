export interface GuiActionMeta {
  id: string;
  label: string;
  requires_simulation: boolean;
  /** True when the server considers this action ready to run right now. */
  is_available: boolean;
  /** Optional tooltip text the plugin supplies for this action's button. */
  description?: string | null;
  /**
   * Optional per-scenario cost estimate (seconds). When set, the Simulate
   * panel multiplies it by the run-set's scenario count and shows an
   * "~Ns expected" toast when this action starts.
   */
  estimated_seconds_per_scenario?: number | null;
}

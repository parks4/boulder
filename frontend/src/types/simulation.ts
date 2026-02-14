/** Time-series data for a single reactor. */
export interface ReactorSeries {
  T: number[];
  P: number[];
  X: Record<string, number[]>;
}

/** Intermediate progress snapshot streamed via SSE. */
export interface SimulationProgress {
  is_running: boolean;
  is_complete: boolean;
  error_message?: string | null;
  times: number[];
  reactors_series: Record<string, ReactorSeries>;
  reactor_reports?: Record<string, unknown>;
}

/** Full results returned on simulation completion. */
export interface SimulationResults extends SimulationProgress {
  code_str?: string;
  summary?: unknown[];
  sankey_links?: Record<string, unknown> | null;
  sankey_nodes?: string[] | null;
  elapsed_time?: number | null;
}

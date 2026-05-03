/** Time-series data for a single reactor. */
export interface ReactorSeries {
  T: number[];
  P: number[];
  X: Record<string, number[]>;
  /** Mass fractions per species (optional for backward compatibility). */
  Y?: Record<string, number[]>;
  /**
   * True when the series represents a spatial (axial) profile (e.g. a plug-flow reactor).
   * In this case `x` holds axial position [m] and `t` holds residence time [s].
   */
  is_spatial?: boolean;
  /** Axial position array [m] — only present when is_spatial is true. */
  x?: number[];
  /** Residence-time array [s] — only present when is_spatial is true. */
  t?: number[];
  /** Per-FBS-iteration heat-loss [kW] — only present when is_spatial is true. */
  fbs_convergence?: number[];
  /** True when the reactor is a Perfectly Stirred Reactor (PSR/CSTR). */
  is_psr?: boolean;
}

/** Connection (e.g. MFC) report from backend: mass and volumetric flow rates. */
export interface ConnectionReport {
  mass_flow_rate?: number;
  volumetric_flow_real_m3_s?: number;
  volumetric_flow_normal_m3_s?: number;
  source_id?: string;
  target_id?: string;
}

/** Intermediate progress snapshot streamed via SSE. */
export interface SimulationProgress {
  is_running: boolean;
  is_complete: boolean;
  error_message?: string | null;
  /** Staged-solver build counters — updated after each stage completes. */
  stages_done?: number;
  n_stages?: number;
  times: number[];
  reactors_series: Record<string, ReactorSeries>;
  reactor_reports?: Record<string, unknown>;
  connection_reports?: Record<string, ConnectionReport>;
  /** Total simulation time in seconds (for progress %). */
  total_time?: number | null;
}

/** Full results returned on simulation completion. */
export interface SimulationResults extends SimulationProgress {
  code_str?: string;
  summary?: unknown[];
  sankey_links?: Record<string, unknown> | null;
  sankey_nodes?: string[] | null;
  elapsed_time?: number | null;
  /** Connections list after post-build hooks, for visual graph sync. */
  updated_connections?: Array<{
    id: string;
    source: string;
    target: string;
    type: string;
    properties: Record<string, unknown>;
  }> | null;
}

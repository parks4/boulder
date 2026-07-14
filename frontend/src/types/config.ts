/** A reactor or reservoir node in the network. */
export interface ConfigNode {
  id: string;
  type: string;
  properties: Record<string, unknown>;
  metadata?: Record<string, unknown> | null;
  group?: string | null;
}

/** A connection (MFC, Valve, Wall) between two nodes. */
export interface ConfigConnection {
  id: string;
  type: string;
  source: string;
  target: string;
  properties: Record<string, unknown>;
  metadata?: Record<string, unknown> | null;
  /** Staged-solving group tag — must be preserved for multi-stage YAML round-trips. */
  group?: string | null;
  /** True when synthesised from a STONE v2 logical (kind-less) inter-stage edge. */
  logical?: boolean | null;
}

/** Per-stage metadata for a multi-stage (STONE v2 `stages:`) config. */
export interface StageGroup {
  stage_order?: number;
  mechanism?: string;
  /** This stage's resolved solver — its own override, or inherited from `settings.solver`. */
  solver?: Record<string, unknown>;
}

/** The normalised reactor-network configuration. */
export interface NormalizedConfig {
  metadata?: Record<string, unknown> | null;
  phases?: Record<string, unknown> | null;
  settings?: Record<string, unknown> | null;
  nodes: ConfigNode[];
  connections: ConfigConnection[];
  output?: unknown;
  /** Present for staged configs; one entry per stage, keyed by stage id. */
  groups?: Record<string, StageGroup> | null;
}

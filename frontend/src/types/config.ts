/** A reactor or reservoir node in the network. */
export interface ConfigNode {
  id: string;
  type: string;
  properties: Record<string, unknown>;
  metadata?: Record<string, unknown> | null;
}

/** A connection (MFC, Valve, Wall) between two nodes. */
export interface ConfigConnection {
  id: string;
  type: string;
  source: string;
  target: string;
  properties: Record<string, unknown>;
  metadata?: Record<string, unknown> | null;
}

/** The normalised reactor-network configuration. */
export interface NormalizedConfig {
  metadata?: Record<string, unknown> | null;
  phases?: Record<string, unknown> | null;
  settings?: Record<string, unknown> | null;
  nodes: ConfigNode[];
  connections: ConfigConnection[];
  output?: unknown;
}

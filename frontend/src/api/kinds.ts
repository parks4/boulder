import { apiFetch } from "./client";

/** One reactor or connection kind this Boulder build can construct. */
export interface KindInfo {
  kind: string;
  /** Cantera doc-link, or null for plugin-registered kinds (no shared doc). */
  doc_url: string | null;
  description: string | null;
}

interface KindsResponse {
  reactors: KindInfo[];
  connections: KindInfo[];
}

/** List every reactor/connection kind the running server can build. */
export function fetchKinds(): Promise<KindsResponse> {
  return apiFetch<KindsResponse>("/ui/kinds");
}

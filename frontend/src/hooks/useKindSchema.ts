import { useEffect, useState } from "react";
import { fetchKindFieldMeta, type FieldMeta } from "@/api/kindSchema";

const cache = new Map<string, Record<string, FieldMeta> | null>();

/**
 * Field metadata (descriptions, enum options, conditional visibility) for a
 * node/connection kind, from the schema its plugin registered. Null while
 * loading or when the kind has no schema. Cached per kind for the session.
 *
 * The return value derives from the module cache; the state is only a
 * version bump that re-renders the caller once a fetch resolves.
 */
export function useKindSchema(
  kind: string,
): Record<string, FieldMeta> | null {
  const [, bump] = useState(0);

  useEffect(() => {
    if (!kind || cache.has(kind)) return;
    let cancelled = false;
    fetchKindFieldMeta(kind)
      .then((fields) => {
        cache.set(kind, fields);
        if (!cancelled) bump((n) => n + 1);
      })
      .catch(() => {
        // Schema lookup is best-effort; the panel degrades to plain fields.
        cache.set(kind, null);
        if (!cancelled) bump((n) => n + 1);
      });
    return () => {
      cancelled = true;
    };
  }, [kind]);

  return kind ? (cache.get(kind) ?? null) : null;
}

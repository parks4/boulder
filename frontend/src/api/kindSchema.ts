import { apiFetch } from "./client";

/** JSON-schema fragment for one property of a node/connection kind. */
export interface FieldMeta {
  description?: string;
  /** Allowed values (from Literal/Enum fields) — rendered as a dropdown. */
  options?: string[];
  /** Show the field only while every referenced sibling has the given value. */
  visibleWhen?: Record<string, unknown>;
}

interface KindSchemaResponse {
  kind: string;
  schema: {
    properties?: Record<string, Record<string, unknown>>;
  } | null;
}

/** Pull the enum options out of a JSON-schema property (incl. Optional[...]). */
function extractOptions(prop: Record<string, unknown>): string[] | undefined {
  if (Array.isArray(prop.enum)) return prop.enum.map(String);
  if (prop.const !== undefined) return [String(prop.const)];
  const anyOf = prop.anyOf;
  if (Array.isArray(anyOf)) {
    for (const variant of anyOf as Record<string, unknown>[]) {
      const nested = extractOptions(variant);
      if (nested) return nested;
    }
  }
  return undefined;
}

/**
 * Field metadata for a node/connection kind, keyed by property name.
 * Resolves to null when the kind has no registered schema.
 */
export async function fetchKindFieldMeta(
  kind: string,
): Promise<Record<string, FieldMeta> | null> {
  const body = await apiFetch<KindSchemaResponse>(
    `/ui/kind-schema/${encodeURIComponent(kind)}`,
  );
  const props = body.schema?.properties;
  if (!props) return null;
  const fields: Record<string, FieldMeta> = {};
  for (const [key, raw] of Object.entries(props)) {
    fields[key] = {
      description:
        typeof raw.description === "string" ? raw.description : undefined,
      options: extractOptions(raw),
      visibleWhen:
        raw.visible_when && typeof raw.visible_when === "object"
          ? (raw.visible_when as Record<string, unknown>)
          : undefined,
    };
  }
  return fields;
}

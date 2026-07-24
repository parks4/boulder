import type { GuiActionMeta } from "@/types/guiAction";
import { apiFetch } from "@/api/client";

export interface GuiActionRunPayload {
  config?: Record<string, unknown> | null;
  config_yaml?: string | null;
  filename?: string | null;
  simulation_id?: string | null;
}

async function parseApiError(res: Response): Promise<string> {
  const body = await res.text();
  try {
    const parsed = JSON.parse(body) as { detail?: string };
    return parsed.detail ?? body;
  } catch {
    return body;
  }
}

/**
 * Fetch GUI action metadata for the currently loaded browser config.
 *
 * Sends the live config/config_yaml/filename/simulation_id (same shape as
 * {@link runGuiAction}) so the server can list actions based on what's
 * actually loaded in the browser — e.g. after "Upload Config" — rather than
 * only the config the server happened to preload at startup.
 */
export async function fetchGuiActions(
  payload: GuiActionRunPayload = {},
): Promise<GuiActionMeta[]> {
  return apiFetch<GuiActionMeta[]>("/gui-actions", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function runGuiAction(
  actionId: string,
  payload: GuiActionRunPayload,
): Promise<{ blob: Blob; filename: string }> {
  const res = await fetch(`/api/gui-actions/${actionId}/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw new Error(`API ${res.status}: ${await parseApiError(res)}`);
  }

  const blob = await res.blob();
  const disposition = res.headers.get("Content-Disposition") ?? "";
  const match = disposition.match(/filename="([^"]+)"/);
  const filename = match?.[1] ?? "download";
  return { blob, filename };
}

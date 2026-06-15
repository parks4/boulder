import type { GuiActionMeta } from "@/types/guiAction";

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

export async function fetchGuiActions(): Promise<GuiActionMeta[]> {
  const res = await fetch("/api/gui-actions");
  if (!res.ok) {
    throw new Error(`API ${res.status}: ${await parseApiError(res)}`);
  }
  return res.json() as Promise<GuiActionMeta[]>;
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

/** Contract of a host status endpoint (`plugins.add_header_status`). */
export type HostStatusTone = "ok" | "warn" | "error" | "neutral";

export interface HostStatus {
  text: string;
  tone: HostStatusTone;
  href?: string;
  tooltip?: string;
}

const TONES: readonly string[] = ["ok", "warn", "error", "neutral"];

/**
 * The same href rule the server applies to header links: a relative path or an
 * http(s) URL, no `//host`, no whitespace or backslash. Anything else is `null`.
 */
export function safeHref(href: unknown): string | null {
  if (typeof href !== "string" || /[\s\\]/.test(href)) return null;
  const relative = href.startsWith("/") && !href.startsWith("//");
  return relative || /^https?:\/\//i.test(href) ? href : null;
}

/**
 * Validate a host's JSON answer. Throws with the reason when it does not match
 * the contract, so the caller can show it instead of hiding the chip.
 */
export function parseHostStatus(data: unknown): HostStatus {
  const d = data as Record<string, unknown> | null;
  if (d === null || typeof d !== "object") throw new Error("response is not an object");
  if (typeof d.text !== "string" || !d.text.trim()) throw new Error("missing text");
  if (typeof d.tone !== "string" || !TONES.includes(d.tone)) {
    throw new Error(`invalid tone ${JSON.stringify(d.tone)}`);
  }
  if (d.tooltip !== undefined && typeof d.tooltip !== "string") {
    throw new Error("tooltip is not a string");
  }
  const out: HostStatus = { text: d.text, tone: d.tone as HostStatusTone };
  if (d.tooltip !== undefined) out.tooltip = d.tooltip as string;
  if (d.href !== undefined) {
    const href = safeHref(d.href);
    if (href === null) throw new Error(`invalid href ${JSON.stringify(d.href)}`);
    out.href = href;
  }
  return out;
}

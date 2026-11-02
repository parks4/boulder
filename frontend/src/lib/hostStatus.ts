/** Answer of `GET /api/ui/header-status` (`plugins.header_status`). */
export type HostStatusTone = "ok" | "warn" | "error" | "neutral";

export interface HostStatus {
  text: string;
  tone: HostStatusTone;
  href: string | null;
  tooltip: string | null;
  new_tab: boolean;
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
 * Validate the server's JSON answer: `{status: null}` is no chip (`null`).
 * Throws with the reason when it does not match the contract, so the caller can
 * show it instead of hiding the chip.
 */
export function parseHostStatus(data: unknown): HostStatus | null {
  const d = data as Record<string, unknown> | null;
  if (d === null || typeof d !== "object") throw new Error("response is not an object");
  if (d.status === null) return null;
  const s = d.status as Record<string, unknown> | undefined;
  if (s === undefined || typeof s !== "object") throw new Error("missing status");
  if (typeof s.text !== "string" || !s.text.trim()) throw new Error("missing text");
  if (typeof s.tone !== "string" || !TONES.includes(s.tone)) {
    throw new Error(`invalid tone ${JSON.stringify(s.tone)}`);
  }
  const tooltip = s.tooltip ?? null;
  if (tooltip !== null && typeof tooltip !== "string") {
    throw new Error("tooltip is not a string");
  }
  let href: string | null = null;
  if (s.href !== undefined && s.href !== null) {
    href = safeHref(s.href);
    if (href === null) throw new Error(`invalid href ${JSON.stringify(s.href)}`);
  }
  return {
    text: s.text,
    tone: s.tone as HostStatusTone,
    href,
    tooltip,
    new_tab: s.new_tab === true,
  };
}

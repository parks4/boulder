/** Base URL for the API – proxied in development via Vite. */
const BASE_URL = "/api";

/** A non-2xx API response: `message` is "API <status>: <detail>", and the
 * parts are kept so the UI can word errors without the raw status prefix. */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(status: number, detail: string) {
    super(`API ${status}: ${detail}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

/** Typed fetch wrapper with automatic JSON parsing and error handling. */
export async function apiFetch<T>(
  endpoint: string,
  options?: RequestInit,
): Promise<T> {
  const url = `${BASE_URL}${endpoint}`;
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });

  if (!res.ok) {
    const body = await res.text();
    let detail: string;
    try {
      const parsed = JSON.parse(body).detail ?? body;
      // FastAPI's own 422s carry a list of validation errors, not a string.
      detail = typeof parsed === "string" ? parsed : JSON.stringify(parsed);
    } catch {
      detail = body;
    }
    throw new ApiError(res.status, detail);
  }

  return res.json() as Promise<T>;
}

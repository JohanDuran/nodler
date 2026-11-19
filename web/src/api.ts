export class ApiError extends Error {
  constructor(public status: number, public detail: unknown) {
    super(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method,
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, data?.detail ?? data ?? res.statusText);
  return data as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  put: <T>(path: string, body: unknown) => request<T>("PUT", path, body),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
  del: <T>(path: string) => request<T>("DELETE", path),
};

export function errorText(e: unknown): string {
  if (e instanceof ApiError) {
    const d = e.detail as { errors?: string[] } | string | { msg: string }[];
    if (typeof d === "string") return d;
    if (Array.isArray(d)) return d.map((x) => x.msg).join("; ");
    if (d && "errors" in d && d.errors) return d.errors.join("\n");
  }
  return String(e);
}

export function ago(t: number | null | undefined): string {
  if (!t) return "—";
  const s = Math.round(Date.now() / 1000 - t);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return new Date(t * 1000).toLocaleDateString();
}

export function duration(a: number, b: number | null): string {
  const s = Math.round((b ?? Date.now() / 1000) - a);
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`;
}

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? "/api/v1").replace(/\/$/, "");
const TOKEN_KEY = "oz.access_token";
const REFRESH_KEY = "oz.refresh_token";
const WORKSPACE_KEY = "oz.workspace_id";

export class ApiError extends Error {
  status: number;
  code: string;
  details: unknown;
  requestId: string | null;

  constructor(
    status: number,
    message: string,
    code = "error",
    details: unknown = null,
    requestId: string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId;
  }
}

export const tokens = {
  access: () => localStorage.getItem(TOKEN_KEY),
  refresh: () => localStorage.getItem(REFRESH_KEY),
  set(access: string, refresh: string) {
    localStorage.setItem(TOKEN_KEY, access);
    localStorage.setItem(REFRESH_KEY, refresh);
  },
  clear() {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(REFRESH_KEY);
    localStorage.removeItem(WORKSPACE_KEY);
  },
};

export const workspaceStore = {
  get: () => localStorage.getItem(WORKSPACE_KEY),
  set: (id: string) => localStorage.setItem(WORKSPACE_KEY, id),
  clear: () => localStorage.removeItem(WORKSPACE_KEY),
};

interface RequestOptions {
  method?: string;
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
  rawBody?: BodyInit;
}

function buildHeaders(body: unknown, extra?: Record<string, string>): HeadersInit {
  const headers: Record<string, string> = { ...(extra ?? {}) };
  const token = tokens.access();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined && !(body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }
  headers["X-Request-ID"] = crypto.randomUUID().replace(/-/g, "").slice(0, 16);
  return headers;
}

async function parseError(response: Response): Promise<ApiError> {
  let code = "error";
  let message = `Request failed with status ${response.status}`;
  let details: unknown = null;
  let requestId: string | null = response.headers.get("X-Request-ID");
  try {
    const payload = await response.json();
    if (payload?.error) {
      code = payload.error.code ?? code;
      message = payload.error.message ?? message;
      details = payload.error.details ?? null;
      requestId = payload.error.request_id ?? requestId;
    }
  } catch {
    // Non-JSON error body: keep the generic message.
  }
  return new ApiError(response.status, message, code, details, requestId);
}

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { body, rawBody, headers, method = "GET", signal } = options;
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      headers: buildHeaders(body, headers),
      body: rawBody ?? (body !== undefined ? JSON.stringify(body) : undefined),
      signal,
    });
  } catch (error) {
    if ((error as Error).name === "AbortError") throw error;
    throw new ApiError(0, "Cannot reach the OPERATION ZERO API. Check that the backend is running.");
  }

  if (response.status === 401) {
    tokens.clear();
    window.dispatchEvent(new CustomEvent("oz:unauthorized"));
    throw await parseError(response);
  }
  if (!response.ok) throw await parseError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export async function apiDownload(
  path: string,
  method = "GET",
): Promise<{ blob: Blob; filename: string }> {
  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers: buildHeaders(undefined),
  });
  if (response.status === 401) {
    tokens.clear();
    window.dispatchEvent(new CustomEvent("oz:unauthorized"));
    throw await parseError(response);
  }
  if (!response.ok) throw await parseError(response);
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const match = /filename="?([^";]+)"?/.exec(disposition);
  return { blob: await response.blob(), filename: match?.[1] ?? "report" };
}

export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 403) return "Your role does not permit this action.";
    return error.requestId ? `${error.message} (request ${error.requestId})` : error.message;
  }
  if (error instanceof Error) return error.message;
  return "Unexpected error";
}

import type { ApiErrorBody } from "./contracts";

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "/api/v1";

export class ApiError extends Error {
  readonly status: number;
  readonly code?: string;
  readonly requestId?: string;
  readonly fieldErrors: Record<string, string[]>;

  constructor(message: string, options: { status: number; body?: ApiErrorBody; requestId?: string }) {
    super(message);
    this.name = "ApiError";
    this.status = options.status;
    this.code = options.body?.code;
    this.requestId = options.body?.request_id ?? options.requestId;
    this.fieldErrors = options.body?.errors ?? {};
  }
}

type ApiRequestOptions = Omit<RequestInit, "body"> & {
  body?: unknown;
  timeoutMs?: number;
};

function requestTarget(baseUrl: string, path: string) {
  return `${baseUrl}${path}`;
}

function browserFailureReason(error: unknown) {
  if (error instanceof Error && error.message.trim()) return error.message.trim();
  return "The browser rejected the request before it reached Chowly.";
}

export function messageFromBody(body: ApiErrorBody | undefined, status: number) {
  if (typeof body?.detail === "string") return body.detail;
  if (body?.detail && typeof body.detail === "object" && body.detail.message) return body.detail.message;
  return status >= 500 ? "Chowly is temporarily unavailable. Please try again." : "The request could not be completed.";
}

function createRequestId() {
  return globalThis.crypto?.randomUUID?.() ?? `web-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export class ApiClient {
  private readonly baseUrl: string;
  private readonly fetcher: typeof fetch;

  constructor(baseUrl = API_BASE_URL, fetcher: typeof fetch = fetch.bind(globalThis)) {
    this.baseUrl = baseUrl;
    this.fetcher = fetcher;
  }

  async request<T>(path: string, options: ApiRequestOptions = {}): Promise<T> {
    const requestId = createRequestId();
    const target = requestTarget(this.baseUrl, path);
    const controller = new AbortController();
    const timeout = globalThis.setTimeout(() => controller.abort(new DOMException("Request timed out", "TimeoutError")), options.timeoutMs ?? 15000);
    const abortParent = () => controller.abort(options.signal?.reason);
    options.signal?.addEventListener("abort", abortParent, { once: true });
    const headers = new Headers(options.headers);
    headers.set("Accept", "application/json");
    headers.set("X-Request-ID", requestId);
    if (options.body !== undefined && !(options.body instanceof FormData)) headers.set("Content-Type", "application/json");

    try {
      console.info("[CHOWLY_API_REQUEST]", { method: options.method ?? "GET", target, requestId });
      const response = await this.fetcher(target, {
        ...options,
        body:
          options.body === undefined || options.body instanceof FormData
            ? (options.body as BodyInit | undefined)
            : JSON.stringify(options.body),
        credentials: "include",
        headers,
        signal: controller.signal,
      });
      const responseRequestId = response.headers.get("X-Request-ID") ?? requestId;
      if (response.status === 204) return undefined as T;
      const body = (await response.json().catch(() => undefined)) as ApiErrorBody | T | undefined;
      if (!response.ok) {
        throw new ApiError(messageFromBody(body as ApiErrorBody | undefined, response.status), {
          status: response.status,
          body: body as ApiErrorBody | undefined,
          requestId: responseRequestId,
        });
      }
      return body as T;
    } catch (error) {
      if (error instanceof ApiError) throw error;
      if (controller.signal.aborted) {
        throw new ApiError(options.signal?.aborted ? "The request was cancelled." : "The request timed out.", {
          status: 0,
          requestId,
        });
      }
      const reason = browserFailureReason(error);
      console.error("[CHOWLY_API_FAILURE]", { method: options.method ?? "GET", target, requestId, reason, error });
      throw new ApiError(`Chowly could not send this request. ${reason}`, {
        status: 0,
        requestId,
      });
    } finally {
      globalThis.clearTimeout(timeout);
      options.signal?.removeEventListener("abort", abortParent);
    }
  }

  get<T>(path: string, options?: ApiRequestOptions) {
    return this.request<T>(path, { ...options, method: "GET" });
  }

  post<T>(path: string, body?: unknown, options?: ApiRequestOptions) {
    return this.request<T>(path, { ...options, method: "POST", body });
  }

  patch<T>(path: string, body?: unknown, options?: ApiRequestOptions) {
    return this.request<T>(path, { ...options, method: "PATCH", body });
  }

  delete<T>(path: string, options?: ApiRequestOptions) {
    return this.request<T>(path, { ...options, method: "DELETE" });
  }
}

export const apiClient = new ApiClient();

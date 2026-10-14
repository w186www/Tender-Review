import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

type ApiCode = components["schemas"]["ErrorCode"];
type ErrorBody = components["schemas"]["Error"];

const TOKEN_KEY = "bidding-compliance.access-token";

export class ApiError extends Error {
  readonly status: number;
  readonly code?: ApiCode;
  readonly requestId?: string;

  constructor(
    status: number,
    message: string,
    code?: ApiCode,
    requestId?: string,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.requestId = requestId;
  }
}

export function readToken(): string | null {
  return window.sessionStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null): void {
  if (token) window.sessionStorage.setItem(TOKEN_KEY, token);
  else window.sessionStorage.removeItem(TOKEN_KEY);
}

const timedFetch: (input: Request) => Promise<Response> = async (input) => {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), 120_000);
  const callerSignal = input.signal;
  const abortFromCaller = () => controller.abort(callerSignal?.reason);
  if (callerSignal?.aborted) controller.abort(callerSignal.reason);
  else callerSignal?.addEventListener("abort", abortFromCaller, { once: true });
  try {
    return await fetch(input, {
      signal: controller.signal,
      cache: "no-store",
    });
  } finally {
    window.clearTimeout(timer);
    callerSignal?.removeEventListener("abort", abortFromCaller);
  }
};

export const client = createClient<paths>({
  baseUrl: new URL("/api/v1", window.location.origin).toString(),
  fetch: timedFetch,
});

client.use({
  onRequest({ request }) {
    const token = readToken();
    if (token) request.headers.set("Authorization", `Bearer ${token}`);
    request.headers.set("Accept", "application/json");
    return request;
  },
  onResponse({ response }) {
    if (response.status === 401) {
      setToken(null);
      window.dispatchEvent(new Event("auth:expired"));
    }
    return response;
  },
});

function apiMessage(status: number, code?: ApiCode): string {
  if (status === 401 || code === "UNAUTHENTICATED")
    return "登录状态已失效，请重新登录。";
  if (status === 403 || code === "FORBIDDEN")
    return "当前账号没有执行此操作的权限。";
  if (status === 404 || code === "NOT_FOUND")
    return "所需内容不存在或当前账号不可见。";
  if (status === 409 || code === "CONFLICT")
    return "数据已被其他操作更新，请刷新后重新确认。";
  if (status === 413 || code === "PAYLOAD_TOO_LARGE")
    return "文件超过系统允许的大小。";
  if (status === 415 || code === "UNSUPPORTED_MEDIA_TYPE")
    return "文件格式不受支持。";
  if (status === 422 || code === "VALIDATION_ERROR")
    return "输入内容未通过校验，请检查必填项和格式。";
  if (status === 429 || code === "RATE_LIMITED")
    return "请求过于频繁，请稍后再试。";
  if (status === 503) return "审查执行服务当前不可用，系统没有生成模拟结果。";
  if (status >= 500) return "服务暂时不可用，请稍后重试。";
  return "请求未能完成，请检查输入后重试。";
}

export async function unwrap<T>(
  request: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const result = await request;
  if (!result.response.ok) {
    const body = (result.error ?? {}) as Partial<ErrorBody>;
    const code = body.code;
    const requestId = body.request_id;
    throw new ApiError(
      result.response.status,
      apiMessage(result.response.status, code),
      code,
      requestId,
    );
  }
  if (result.data === undefined)
    throw new ApiError(500, "服务未返回可用数据。");
  return result.data;
}

export function errorText(error: unknown): string {
  if (error instanceof ApiError) {
    return error.requestId
      ? `${error.message}（请求编号：${error.requestId}）`
      : error.message;
  }
  if (error instanceof DOMException && error.name === "AbortError") {
    return "请求已取消或等待超时；请刷新状态后再决定是否重试。";
  }
  if (error instanceof TypeError) return "网络连接失败，请检查服务状态后重试。";
  return "发生未知错误，请稍后重试。";
}

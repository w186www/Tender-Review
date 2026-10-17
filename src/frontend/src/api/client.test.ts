import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, errorText, readToken, setToken } from "./client";
import { api } from "./operations";

describe("authorized API client", () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.restoreAllMocks();
  });

  it("clears an expired tab session when the server rejects the token", async () => {
    setToken("short-lived-test-token");
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          code: "UNAUTHENTICATED",
          message: "hidden",
          request_id: "req-test",
        }),
        {
          status: 401,
          headers: { "Content-Type": "application/json" },
        },
      ),
    );
    const expired = vi.fn();
    window.addEventListener("auth:expired", expired);
    try {
      await expect(api.identity()).rejects.toMatchObject({
        status: 401,
        requestId: "req-test",
      });
      expect(readToken()).toBeNull();
      expect(expired).toHaveBeenCalledTimes(1);
      expect(fetchSpy).toHaveBeenCalledTimes(1);
      const request = fetchSpy.mock.calls[0]?.[0];
      const headers =
        request instanceof Request
          ? request.headers
          : new Headers(fetchSpy.mock.calls[0]?.[1]?.headers);
      expect(headers.get("Authorization")).toBe(
        "Bearer short-lived-test-token",
      );
    } finally {
      window.removeEventListener("auth:expired", expired);
    }
  });

  it("maps authorization and version conflicts to concise Chinese messages", () => {
    expect(
      errorText(new ApiError(403, "当前账号没有执行此操作的权限。")),
    ).toContain("没有执行此操作的权限");
    expect(
      errorText(new ApiError(409, "数据已被其他操作更新，请刷新后重新确认。")),
    ).toContain("刷新后重新确认");
  });

  it("aborts a read request when its caller cancels and does not retry", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(
      (_input, init) =>
        new Promise((_resolve, reject) => {
          const signal = init?.signal;
          const abort = () =>
            reject(signal?.reason ?? new DOMException("Aborted", "AbortError"));
          if (signal?.aborted) abort();
          else signal?.addEventListener("abort", abort, { once: true });
        }),
    );
    const controller = new AbortController();
    const pending = api.identity({ signal: controller.signal });
    controller.abort();
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });
});

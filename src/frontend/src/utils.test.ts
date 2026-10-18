import { beforeEach, describe, expect, it } from "vitest";
import { clearIntentKey, intentKey, REVIEW_TIMEOUT_NOTICE } from "./utils";

describe("idempotency keys and review-timeout guidance", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it("reuses one key across retries until the mutation is confirmed", () => {
    const first = intentKey("review:project-1");
    // A retry after a timeout or a refresh must send the same key, so the server can return
    // the persisted task instead of starting a second one.
    expect(intentKey("review:project-1")).toBe(first);
    expect(intentKey("review:project-2")).not.toBe(first);
    clearIntentKey("review:project-1");
    expect(intentKey("review:project-1")).not.toBe(first);
  });

  it("guides the user to the persisted task list after a 120-second abort", () => {
    expect(REVIEW_TIMEOUT_NOTICE).toContain("120 秒");
    expect(REVIEW_TIMEOUT_NOTICE).toContain("不代表任务丢失");
    expect(REVIEW_TIMEOUT_NOTICE).toContain("「审查任务」列表");
    expect(REVIEW_TIMEOUT_NOTICE).toContain("不会重复创建任务");
  });
});

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { EmptyState, Notice, StatusBadge } from "./ui";

describe("workbench status and feedback", () => {
  it("renders processing state with Chinese text and a status announcement", () => {
    render(<StatusBadge status="waiting_human" />);
    expect(screen.getByRole("status").textContent).toBe("等待人工复核");
  });

  it("distinguishes document receipt from human review acceptance", () => {
    const { rerender } = render(<StatusBadge status="accepted" />);
    expect(screen.getByRole("status").textContent).toBe("已接收");
    rerender(<StatusBadge status="accepted" label="已接受人工处理" />);
    expect(screen.getByRole("status").textContent).toBe("已接受人工处理");
  });

  it("announces service errors and provides an accessible empty state", () => {
    const { rerender } = render(
      <Notice kind="error">当前账号没有执行此操作的权限。</Notice>,
    );
    expect(screen.getByRole("alert").textContent).toContain(
      "没有执行此操作的权限",
    );
    rerender(
      <EmptyState title="暂无报告" description="发布结果后可以生成报告。" />,
    );
    expect(screen.getByRole("heading", { name: "暂无报告" })).toBeTruthy();
  });
});

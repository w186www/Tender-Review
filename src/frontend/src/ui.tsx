import type { ButtonHTMLAttributes, ReactNode } from "react";
import { useEffect, useRef } from "react";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "quiet" | "danger";
};

export function Button({
  variant = "secondary",
  className = "",
  ...props
}: ButtonProps) {
  return (
    <button
      className={`button button-${variant} ${className}`.trim()}
      {...props}
    />
  );
}

export function PageHeading({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        {eyebrow && <p className="eyebrow">{eyebrow}</p>}
        <h1>{title}</h1>
        {description && <p className="page-description">{description}</p>}
      </div>
      {actions && <div className="heading-actions">{actions}</div>}
    </div>
  );
}

export function Loading({ label = "正在加载" }: { label?: string }) {
  return (
    <div className="loading-block" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

export function Notice({
  kind,
  children,
}: {
  kind: "error" | "success" | "info";
  children: ReactNode;
}) {
  return (
    <div
      className={`notice notice-${kind}`}
      role={kind === "error" ? "alert" : "status"}
    >
      {children}
    </div>
  );
}

const statusText: Record<string, string> = {
  quarantined: "安全检查中",
  accepted: "已接收",
  rejected: "已拒绝",
  parsing: "解析中",
  needs_review: "需要人工检查",
  needs_confirmation: "等待上下文确认",
  ready: "可用于审查",
  failed: "处理失败",
  queued: "已排队",
  running: "执行中",
  waiting_human: "等待人工复核",
  result_published: "结果已发布",
  cancelled: "已取消",
  pending: "待复核",
  accepted_review: "已接受人工处理",
  modified: "已修改并复核",
  rejected_review: "已驳回候选项",
};

export function StatusBadge({
  status,
  label: customLabel,
}: {
  status: string;
  label?: string;
}) {
  const label = customLabel || statusText[status] || "状态未知";
  return (
    <span
      className={`status-badge status-${status}`}
      role="status"
      aria-live="polite"
    >
      {label}
    </span>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <span className="empty-mark" aria-hidden="true">
        —
      </span>
      <h2>{title}</h2>
      <p>{description}</p>
      {action}
    </div>
  );
}

export function Dialog({
  open,
  title,
  onClose,
  children,
  size = "normal",
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  size?: "normal" | "wide";
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useRef(`dialog-title-${crypto.randomUUID()}`);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    else if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      className={`modal modal-${size}`}
      aria-labelledby={titleId.current}
      onClose={onClose}
    >
      <div className="modal-header">
        <h2 id={titleId.current}>{title}</h2>
        <button
          className="icon-button"
          type="button"
          aria-label="关闭弹窗"
          onClick={() => ref.current?.close()}
        >
          ×
        </button>
      </div>
      <div className="modal-content">{children}</div>
    </dialog>
  );
}

export function DataTable({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <section className="table-scroll" aria-label={label}>
      <table>{children}</table>
    </section>
  );
}

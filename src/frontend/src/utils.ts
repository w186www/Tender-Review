const INTENT_PREFIX = "bidding-compliance.intent.";

export function intentKey(scope: string): string {
  const key = `${INTENT_PREFIX}${scope}`;
  const existing = window.sessionStorage.getItem(key);
  if (existing) return existing;
  const created = crypto.randomUUID();
  window.sessionStorage.setItem(key, created);
  return created;
}

export function clearIntentKey(scope: string): void {
  window.sessionStorage.removeItem(`${INTENT_PREFIX}${scope}`);
}

export function formatBytes(size?: number | null): string {
  if (size === undefined || size === null) return "大小未提供";
  if (size < 1024) return `${size} 字节`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatDate(value?: string | null): string {
  if (!value) return "时间未提供";
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return "时间格式不可识别";
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function apiEnumLabel(value: string): string {
  const labels: Record<string, string> = {
    qualification: "资格条件",
    technical: "技术参数",
    evaluation: "评标办法",
    contract: "合同条款",
    procedure: "采购程序",
    candidate: "候选线索",
    suspected: "疑似问题",
    insufficient_evidence: "证据不足",
    confirmed: "系统证据状态：确认",
    low: "低",
    medium: "中",
    high: "高",
    critical: "严重",
    pending: "待复核",
    accepted: "人工已接受处理",
    modified: "人工已修改处理",
    rejected: "人工已驳回候选项",
    accept: "接受处理",
    modify: "修改处理",
    reject: "驳回候选项",
    confirm_no_findings: "确认无待复核项目",
    queued: "已排队",
    running: "执行中",
    waiting_human: "等待人工复核",
    result_published: "结果已发布",
    failed: "处理失败",
    cancelled: "已取消",
    government: "政府采购",
    enterprise: "企业采购",
    other: "其他",
    works: "工程",
    goods: "货物",
    services: "服务",
    tender: "招标",
    non_tender: "非招标",
    unknown: "未指定",
  };
  return labels[value] || value;
}

export function saveBlob(blob: Blob, filename: string): void {
  const safeName = Array.from(filename.replace(/[\\/:*?"<>|]/g, "_"))
    .filter((character) => {
      const code = character.codePointAt(0) ?? 0;
      return code >= 0x20 && !(code >= 0x7f && code <= 0x9f);
    })
    .join("")
    .slice(0, 120);
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = safeName;
  anchor.rel = "noopener";
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

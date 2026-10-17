import type { FormEvent } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiError, errorText } from "../api/client";
import {
  api,
  type CitationLocation,
  type DocumentRecord,
  type ReviewTask,
} from "../api/operations";
import type { components } from "../api/schema";
import { useAuth } from "../auth";
import {
  Button,
  DataTable,
  EmptyState,
  Loading,
  Notice,
  PageHeading,
  StatusBadge,
} from "../ui";
import {
  apiEnumLabel,
  clearIntentKey,
  formatDate,
  intentKey,
  saveBlob,
} from "../utils";

type Finding = components["schemas"]["RiskFinding"];
type FindingsResponse = components["schemas"]["ReviewFindings"];
type ReviewDecision = components["schemas"]["ReviewDecision"];
type PendingReview = components["schemas"]["PendingReview"];

const severityClass: Record<string, string> = {
  low: "severity-low",
  medium: "severity-medium",
  high: "severity-high",
  critical: "severity-critical",
};
// Mirrors the server's bounded-retry policy: a provider can emit a non-conforming
// structured response for one batch, and replaying it reuses every accepted batch.
const retryableFailures = new Set([
  "timeout",
  "rate_limited",
  "provider_unavailable",
  "provider_error",
  "response_invalid",
]);

export function PendingReviewsPage() {
  const [items, setItems] = useState<PendingReview[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [refresh, setRefresh] = useState(0);

  // biome-ignore lint/correctness/useExhaustiveDependencies: refresh intentionally reloads the server list after a user refresh.
  useEffect(() => {
    let active = true;
    setLoading(true);
    api
      .pendingReviews(offset, 50)
      .then((response) => {
        if (!active) return;
        setItems(response.items);
        setError(null);
      })
      .catch((reason: unknown) => active && setError(errorText(reason)))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [offset, refresh]);

  return (
    <section className="page-wrap">
      <PageHeading
        eyebrow="人工复核"
        title="待复核任务"
        description="只显示服务端当前处于等待人工复核状态的持久化任务。"
        actions={
          <Button onClick={() => setRefresh((value) => value + 1)}>
            刷新状态
          </Button>
        }
      />
      {error && <Notice kind="error">{error}</Notice>}
      {loading ? (
        <Loading label="正在读取待复核任务" />
      ) : items.length === 0 ? (
        <EmptyState
          title="当前没有待复核任务"
          description="当审查流程需要人工判断时，任务会出现在这里。"
        />
      ) : (
        <DataTable label="待复核任务列表">
          <thead>
            <tr>
              <th scope="col">任务编号</th>
              <th scope="col">项目</th>
              <th scope="col">创建时间</th>
              <th scope="col">任务状态</th>
              <th scope="col">操作</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={`${item.review_task_id}-${item.run_id}`}>
                <td>
                  <code>{item.review_task_id}</code>
                </td>
                <td>
                  <code>{item.project_id}</code>
                </td>
                <td>{formatDate(item.created_at)}</td>
                <td>
                  <StatusBadge status={item.status} />
                </td>
                <td>
                  <Link
                    className="table-link"
                    to={`/reviews/${encodeURIComponent(item.review_task_id)}/${encodeURIComponent(item.run_id)}`}
                  >
                    打开复核
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </DataTable>
      )}
      <div className="pagination">
        <Button
          disabled={offset === 0 || loading}
          onClick={() => setOffset(Math.max(0, offset - 50))}
        >
          上一页
        </Button>
        <Button
          disabled={loading || items.length < 50}
          onClick={() => setOffset(offset + 50)}
        >
          下一页
        </Button>
      </div>
    </section>
  );
}

export function ReviewPage() {
  const { reviewTaskId = "", runId = "" } = useParams();
  const { identity } = useAuth();
  const navigate = useNavigate();
  const [task, setTask] = useState<ReviewTask | null>(null);
  const [data, setData] = useState<FindingsResponse | null>(null);
  const [history, setHistory] = useState<ReviewDecision[]>([]);
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [reports, setReports] = useState<
    components["schemas"]["ReportMetadata"][]
  >([]);
  const [citationMap, setCitationMap] = useState<
    Record<string, CitationLocation[]>
  >({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);

  const reload = useCallback(() => setRefresh((value) => value + 1), []);
  // biome-ignore lint/correctness/useExhaustiveDependencies: refresh intentionally reloads all task, finding, history, and report state.
  useEffect(() => {
    if (!reviewTaskId || !runId) return;
    let active = true;
    let timer: number | undefined;
    const controller = new AbortController();
    const load = async () => {
      try {
        const [current, findings, decisions] = await Promise.all([
          api.review(reviewTaskId, { signal: controller.signal }),
          api.findings(reviewTaskId, runId, { signal: controller.signal }),
          api.reviewHistory(reviewTaskId, runId, { signal: controller.signal }),
        ]);
        if (!active) return;
        setTask(current);
        setData(findings);
        setHistory(decisions.decisions);
        setError(null);
        setLoading(false);
        if (current.status === "queued" || current.status === "running") {
          timer = window.setTimeout(
            () => setRefresh((value) => value + 1),
            1500,
          );
        }
        if (current.project_id) {
          const docs = await api.documents(current.project_id, 0, 100, {
            signal: controller.signal,
          });
          if (active) setDocuments(docs.items);
        }
        if (current.result_id) {
          const reportList = await api.reports(current.result_id, {
            signal: controller.signal,
          });
          if (active) setReports(reportList.items);
        }
      } catch (reason) {
        if (!active) return;
        setError(errorText(reason));
        setLoading(false);
      }
    };
    void load();
    return () => {
      active = false;
      controller.abort();
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [reviewTaskId, runId, refresh]);

  const pending = data?.pending_finding_ids ?? [];
  const counts = useMemo(() => {
    const rows = data?.findings ?? [];
    return {
      total: rows.length,
      pending: rows.filter((item) => item.review_status === "pending").length,
      candidate: rows.filter((item) => item.evidence_status === "candidate")
        .length,
      suspected: rows.filter((item) => item.evidence_status === "suspected")
        .length,
      insufficient: rows.filter(
        (item) => item.evidence_status === "insufficient_evidence",
      ).length,
      confirmed: rows.filter((item) => item.evidence_status === "confirmed")
        .length,
    };
  }, [data]);

  async function publish() {
    if (!data || pending.length > 0) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await api.publish(reviewTaskId, runId);
      setNotice(
        `结果版本 ${result.result_id} 已发布，快照哈希 ${result.content_hash}。`,
      );
      reload();
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(false);
    }
  }

  async function resumeReview() {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const updated = await api.resume(reviewTaskId, runId);
      setNotice(
        `审查流程已继续，服务端当前状态：${apiEnumLabel(updated.status)}。`,
      );
      reload();
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(false);
    }
  }

  async function retryReview() {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const updated = await api.retryReview(reviewTaskId, runId);
      setNotice(
        `有界重试已完成，服务端当前状态：${apiEnumLabel(updated.status)}。`,
      );
      reload();
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(false);
    }
  }

  async function createReport(format: "docx" | "pdf") {
    if (!task?.result_id) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    const scope = `report:${task.result_id}:${format}`;
    try {
      const report = await api.createReport(
        task.result_id,
        format,
        intentKey(scope),
      );
      clearIntentKey(scope);
      setNotice(
        `${format.toUpperCase()} 报告已生成，报告编号 ${report.report_id}。`,
      );
      const updated = await api.reports(task.result_id);
      setReports(updated.items);
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(false);
    }
  }

  async function downloadReport(
    report: components["schemas"]["ReportMetadata"],
  ) {
    setBusy(true);
    setError(null);
    try {
      const blob = await api.downloadReport(report.report_id);
      const demoPrefix =
        import.meta.env.VITE_REVIEW_MODE === "offline-deterministic"
          ? "离线确定性演示-"
          : "";
      saveBlob(
        blob,
        `${demoPrefix}审查报告-${report.report_id}.${report.format}`,
      );
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(false);
    }
  }

  async function showCitations(finding: Finding) {
    setError(null);
    try {
      const result = await api.citations(
        reviewTaskId,
        runId,
        finding.finding_id,
      );
      setCitationMap((current) => ({
        ...current,
        [finding.finding_id]: result.items,
      }));
    } catch (reason) {
      setError(errorText(reason));
    }
  }

  async function downloadSource(citation: CitationLocation) {
    const document = documents.find(
      (item) => item.document_id === citation.document_id,
    );
    if (!document || !task) return;
    setBusy(true);
    setError(null);
    try {
      const blob = await api.originalDocument(
        task.project_id,
        citation.document_id,
      );
      saveBlob(
        blob,
        `原始证据-${citation.document_id}.${document.file_format}`,
      );
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(false);
    }
  }

  if (loading)
    return (
      <section className="page-wrap">
        <Loading label="正在恢复服务端审查结果、复核历史和版本" />
      </section>
    );
  if (!task || !data)
    return (
      <section className="page-wrap">
        <Notice kind="error">{error || "审查任务或结果不可见。"}</Notice>
        <Button onClick={() => navigate(-1)}>返回</Button>
      </section>
    );

  return (
    <section className="page-wrap">
      <PageHeading
        eyebrow="审查结果与人工复核"
        title="审查任务详情"
        description={`任务 ${task.review_task_id} · 批次 ${task.run_id}`}
        actions={<Button onClick={reload}>刷新服务端状态</Button>}
      />
      {error && <Notice kind="error">{error}</Notice>}
      {notice && <Notice kind="success">{notice}</Notice>}
      {task.model_runtime && (
        <div className="panel" data-testid="actual-model-runtime">
          <h2>实际 AI 运行记录</h2>
          <p>
            模式：{task.model_runtime.execution_mode} · 供应商：
            {task.model_runtime.provider || "尚无已验证响应"} · 模型：
            {task.model_runtime.model || "尚无已验证响应"}
          </p>
          <p>
            已验证调用 {task.model_runtime.model_calls} 次 · 输入/输出 tokens：
            {task.model_runtime.input_tokens}/{task.model_runtime.output_tokens}{" "}
            · 估算费用 ¥{task.model_runtime.estimated_cost_cny.toFixed(6)}
          </p>
          <p>
            Skills 候选 {task.model_runtime.skill_candidate_count} 项 · AI
            独立候选 {task.model_runtime.model_candidate_count}{" "}
            项。疑点须结合原文和适用法规人工核验。
          </p>
          <p>
            检索向量模型：{task.model_runtime.embedding_model || "未记录"} ·
            向量索引：
            {task.model_runtime.vector_index_build_id || "未启用神经向量索引"}
          </p>
        </div>
      )}
      <div className="panel review-overview">
        <div>
          <span className="muted">任务状态</span>
          <p>
            <StatusBadge status={task.status} />
          </p>
        </div>
        <div>
          <span className="muted">项目</span>
          <p>
            <Link to={`/projects/${encodeURIComponent(task.project_id)}`}>
              {task.project_id}
            </Link>
          </p>
        </div>
        <div>
          <span className="muted">创建时间</span>
          <p>{formatDate(task.created_at)}</p>
        </div>
        <div>
          <span className="muted">输入快照</span>
          <p>
            <code className="hash-wrap">{task.snapshot_hash}</code>
          </p>
        </div>
        {task.failure_code && (
          <div className="review-failure">
            <span className="muted">失败状态</span>
            <p>{apiEnumLabel(task.failure_code)}</p>
            <small>
              任务失败状态来自服务端。系统没有生成模拟结果；如需重试，请仅在页面给出有界重试操作时使用。
            </small>
          </div>
        )}
      </div>
      {identity?.role === "reviewer" &&
        task.status === "waiting_human" &&
        pending.length === 0 && (
          <div className="review-start-row">
            <span className="muted">
              人工决定已齐全，可以从持久化的 LangGraph 中断继续流程。
            </span>
            <Button
              variant="secondary"
              disabled={busy}
              onClick={() => void resumeReview()}
            >
              继续审查流程
            </Button>
          </div>
        )}
      {identity?.role === "reviewer" &&
        task.status === "failed" &&
        task.retry_count < 2 &&
        task.failure_code &&
        retryableFailures.has(task.failure_code) && (
          <div className="review-start-row">
            <span className="muted">
              服务端允许最多两次的有界重试，当前已重试 {task.retry_count} 次。
            </span>
            <Button
              variant="secondary"
              disabled={busy}
              onClick={() => void retryReview()}
            >
              重试审查
            </Button>
          </div>
        )}
      <div className="summary-grid summary-grid-small">
        <div className="summary-card">
          <span>风险条目</span>
          <strong>{counts.total}</strong>
        </div>
        <div className="summary-card">
          <span>待人工处理</span>
          <strong>{pending.length}</strong>
        </div>
        <div className="summary-card">
          <span>候选 / 疑似</span>
          <strong>
            {counts.candidate} / {counts.suspected}
          </strong>
        </div>
        <div className="summary-card">
          <span>证据不足 / 系统证据确认</span>
          <strong>
            {counts.insufficient} / {counts.confirmed}
          </strong>
        </div>
      </div>
      <section className="panel" aria-labelledby="findings-heading">
        <div className="section-heading">
          <div>
            <h2 id="findings-heading">风险与证据</h2>
            <p className="muted">
              证据状态和复核状态分别展示；人工接受不等于法律结论确认。
            </p>
          </div>
        </div>
        {data.findings.length === 0 ? (
          <EmptyState
            title="服务端未返回风险条目"
            description={
              pending.includes("__review_complete__")
                ? "发布前需要审核员明确确认本次没有待复核项目。"
                : "该结果快照没有可展示的风险条目。"
            }
          />
        ) : (
          <div className="finding-list">
            {data.findings.map((finding) => (
              <FindingCard
                key={finding.finding_id}
                finding={finding}
                citations={citationMap[finding.finding_id]}
                canReview={
                  identity?.role === "reviewer" &&
                  task.status === "waiting_human" &&
                  pending.includes(finding.finding_id)
                }
                snapshotHash={data.snapshot_hash}
                onCitations={() => void showCitations(finding)}
                onDecision={async (decision, reason, modified) => {
                  const scope = `decision:${reviewTaskId}:${runId}:${finding.finding_id}`;
                  setBusy(true);
                  setError(null);
                  setNotice(null);
                  try {
                    await api.decide(
                      reviewTaskId,
                      runId,
                      finding.finding_id,
                      {
                        decision,
                        reason,
                        expected_snapshot_hash: data.snapshot_hash,
                        modified_finding: modified || null,
                      },
                      intentKey(scope),
                    );
                    clearIntentKey(scope);
                    setNotice(
                      "复核决定已由服务端保存并进入审计。请核对更新后的状态。",
                    );
                    reload();
                  } catch (reasonValue) {
                    if (
                      reasonValue instanceof ApiError &&
                      [409, 422].includes(reasonValue.status)
                    )
                      clearIntentKey(scope);
                    setError(errorText(reasonValue));
                  } finally {
                    setBusy(false);
                  }
                }}
                onDownloadSource={(citation) => void downloadSource(citation)}
              />
            ))}
          </div>
        )}
        {pending.includes("__review_complete__") &&
          identity?.role === "reviewer" &&
          task.status === "waiting_human" && (
            <NoFindingConfirmation
              busy={busy}
              snapshotHash={data.snapshot_hash}
              reviewTaskId={reviewTaskId}
              runId={runId}
              onDone={() => {
                setNotice("空结果已由审核员确认并记录。");
                reload();
              }}
              onError={setError}
            />
          )}
        {identity?.role === "reviewer" && task.status === "waiting_human" && (
          <div className="review-start-row">
            <span className="muted">
              发布要求：所有待复核条目均已有服务端决定。
            </span>
            <Button
              variant="primary"
              disabled={busy || pending.length > 0}
              onClick={() => void publish()}
            >
              发布不可变结果版本
            </Button>
          </div>
        )}
      </section>
      {task.result_id && (
        <section className="panel" aria-labelledby="reports-heading">
          <div className="section-heading">
            <div>
              <h2 id="reports-heading">结果版本与报告</h2>
              <p className="muted">
                结果版本 <code>{task.result_id}</code>
              </p>
            </div>
            {identity?.role === "reviewer" && (
              <div className="button-row">
                <Button
                  disabled={busy}
                  onClick={() => void createReport("docx")}
                >
                  生成 Word
                </Button>
                <Button
                  disabled={busy}
                  onClick={() => void createReport("pdf")}
                >
                  生成 PDF
                </Button>
              </div>
            )}
          </div>
          {reports.length === 0 ? (
            <p className="empty-inline">当前结果尚无已生成报告。</p>
          ) : (
            <DataTable label="已生成报告列表">
              <thead>
                <tr>
                  <th scope="col">格式</th>
                  <th scope="col">报告编号</th>
                  <th scope="col">模板</th>
                  <th scope="col">内容哈希</th>
                  <th scope="col">生成时间</th>
                  <th scope="col">操作</th>
                </tr>
              </thead>
              <tbody>
                {reports.map((report) => (
                  <tr key={report.report_id}>
                    <td>{report.format.toUpperCase()}</td>
                    <td>
                      <code>{report.report_id}</code>
                    </td>
                    <td>{report.template_version}</td>
                    <td>
                      <code className="hash-short">
                        {report.content_hash.slice(0, 16)}…
                      </code>
                    </td>
                    <td>{formatDate(report.created_at)}</td>
                    <td>
                      {(identity?.role === "reviewer" ||
                        identity?.role === "auditor") && (
                        <Button
                          variant="quiet"
                          disabled={busy}
                          onClick={() => void downloadReport(report)}
                        >
                          下载报告
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </DataTable>
          )}
        </section>
      )}
      <section className="panel" aria-labelledby="history-heading">
        <div className="section-heading">
          <div>
            <h2 id="history-heading">人工决定历史</h2>
            <p className="muted">历史来自服务端不可变决定记录。</p>
          </div>
        </div>
        {history.length === 0 ? (
          <p className="empty-inline">暂无人工决定记录。</p>
        ) : (
          <DataTable label="人工复核历史">
            <thead>
              <tr>
                <th scope="col">风险编号</th>
                <th scope="col">决定</th>
                <th scope="col">理由</th>
                <th scope="col">审核员</th>
                <th scope="col">时间</th>
              </tr>
            </thead>
            <tbody>
              {history.map((row) => (
                <tr key={row.decision_id}>
                  <td>
                    <code>{row.finding_id}</code>
                  </td>
                  <td>{apiEnumLabel(row.decision)}</td>
                  <td>{row.reason}</td>
                  <td>{row.reviewer_id}</td>
                  <td>{formatDate(row.decided_at)}</td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        )}
      </section>
    </section>
  );
}

function FindingCard({
  finding,
  citations,
  canReview,
  snapshotHash,
  onCitations,
  onDecision,
  onDownloadSource,
}: {
  finding: Finding;
  citations?: CitationLocation[];
  canReview: boolean;
  snapshotHash: string;
  onCitations: () => void;
  onDecision: (
    decision: "accept" | "modify" | "reject",
    reason: string,
    modified?: NonNullable<
      components["schemas"]["ReviewDecisionRequest"]["modified_finding"]
    >,
  ) => Promise<void>;
  onDownloadSource: (citation: CitationLocation) => void;
}) {
  const [decision, setDecision] = useState<"accept" | "modify" | "reject">(
    "accept",
  );
  const [reason, setReason] = useState("");
  const [title, setTitle] = useState(finding.title);
  const [description, setDescription] = useState(finding.description);
  const [severity, setSeverity] = useState(finding.severity);
  const [recommendation, setRecommendation] = useState(finding.recommendation);
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!reason.trim()) return;
    const modified =
      decision === "modify"
        ? {
            title: title.trim(),
            description: description.trim(),
            severity,
            recommendation: recommendation.trim(),
          }
        : undefined;
    setSubmitting(true);
    try {
      await onDecision(decision, reason.trim(), modified);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <article className="finding-card">
      <div className="finding-topline">
        <span className="finding-category">
          {apiEnumLabel(finding.category)}
        </span>
        <span
          className={`severity-tag ${severityClass[finding.severity] || ""}`}
        >
          {apiEnumLabel(finding.severity)}严重程度
        </span>
        <StatusBadge status={finding.review_status} />
      </div>
      <h3>{finding.title}</h3>
      <p className="finding-description">{finding.description}</p>
      <div className="finding-facts">
        <div>
          <span>证据状态</span>
          <strong>{apiEnumLabel(finding.evidence_status)}</strong>
        </div>
        <div>
          <span>分析来源</span>
          <strong>{finding.sources.map(apiEnumLabel).join("、")}</strong>
        </div>
        <div>
          <span>规则编号</span>
          <strong>{finding.rule_ids?.join("、") || "服务端未提供"}</strong>
        </div>
        {finding.confidence !== null && finding.confidence !== undefined && (
          <div>
            <span>置信度</span>
            <strong>{Math.round(finding.confidence * 100)}%</strong>
          </div>
        )}
      </div>
      <div className="finding-detail">
        <h4>原因与建议</h4>
        <p>{finding.reasoning_summary || finding.description}</p>
        <p>
          <strong>建议：</strong>
          {finding.recommendation}
        </p>
      </div>
      {finding.source_excerpt && (
        <div className="quote-block">
          <span>风险原文摘录</span>
          <blockquote>{finding.source_excerpt.quote}</blockquote>
          <small>来源 SHA-256 {finding.source_excerpt.source_hash}</small>
        </div>
      )}
      {finding.evidence?.length > 0 && (
        <div className="evidence-refs">
          <h4>文档与法规证据引用</h4>
          <ul>
            {finding.evidence.map((item) => (
              <li key={`${item.evidence_id}:${item.source_hash}`}>
                <strong>
                  {item.title} · {apiEnumLabel(item.kind)}
                </strong>
                {item.article && <span>{item.article}</span>}
                <code>
                  {item.evidence_id} · SHA-256 {item.source_hash}
                </code>
                <span>{item.quote}</span>
                <small>
                  版本状态：{apiEnumLabel(item.version_status)}
                  {item.page ? ` · 第 ${item.page} 页` : ""}
                  {item.locator ? ` · ${item.locator}` : ""}
                </small>
              </li>
            ))}
          </ul>
        </div>
      )}
      {finding.legal_references && finding.legal_references.length > 0 && (
        <div className="evidence-refs">
          <h4>可能相关法规（适用性未经确认，仅供参考，不计入已核验证据）</h4>
          <ul>
            {finding.legal_references.map((item) => {
              const reference = item as {
                evidence_id?: string;
                title?: string;
                article?: string | null;
                quote?: string;
                source_uri?: string;
                version_status?: string;
                confirmation_reason?: string;
              };
              const referenceKey = `${reference.evidence_id ?? reference.title ?? "reference"}:${
                reference.article ?? "no-article"
              }`;
              return (
                <li key={referenceKey}>
                  <strong>
                    {reference.title ?? "参考法规"}
                    {reference.article ? ` · ${reference.article}` : ""}
                  </strong>
                  {reference.quote && <span>{reference.quote}</span>}
                  {reference.source_uri && <code>{reference.source_uri}</code>}
                  <small>
                    版本核验：
                    {apiEnumLabel(reference.version_status ?? "unverified")}
                    {" · "}适用性：待确认
                    {reference.confirmation_reason
                      ? `（${apiEnumLabel(reference.confirmation_reason)}）`
                      : ""}
                    {" · "}
                    仍需人工核验：该条文尚未完成版本与适用性核验，不能作为违反依据。
                  </small>
                </li>
              );
            })}
          </ul>
        </div>
      )}
      <div className="citation-actions">
        <Button onClick={onCitations}>查询服务端精确定位</Button>
        {citations && citations.length === 0 && (
          <span className="muted">
            服务端未能验证可用定位；页面不会按文字搜索推断位置。
          </span>
        )}
      </div>
      {citations && citations.length > 0 && (
        <section className="citation-list" aria-label="服务端精确原文位置">
          {citations.map((cite) => (
            <div
              className="citation-card"
              key={`${cite.document_id}:${cite.section_id}:${cite.section_revision}`}
            >
              <div className="citation-heading">
                <strong>文档 {cite.document_id}</strong>
                <Button
                  variant="quiet"
                  onClick={() => {
                    onDownloadSource(cite);
                  }}
                >
                  下载原文
                </Button>
              </div>
              <p>
                源文件 SHA-256 <code>{cite.raw_source_sha256}</code>
              </p>
              <p>
                解析版本 P{cite.parse_version} · 章节修订{" "}
                {cite.section_revision} ·{" "}
                {cite.page ? `第 ${cite.page} 页` : "未提供页码"}
              </p>
              <p>
                坐标系统 {apiEnumLabel(cite.coordinate_system)} · 定位{" "}
                {cite.locator}
                {cite.bbox ? ` · 框 ${cite.bbox.join(", ")}` : ""}
              </p>
              <blockquote>{cite.quote}</blockquote>
              <small>摘录 SHA-256 {cite.quote_sha256}</small>
            </div>
          ))}
        </section>
      )}
      {canReview && (
        <form
          className="decision-form"
          onSubmit={(event) => void submit(event)}
        >
          <h4>提交人工复核决定</h4>
          <p className="muted">
            当前输入快照：<code>{snapshotHash}</code>
            。决定和理由将由服务端追加保存。
          </p>
          <fieldset>
            <legend>决定</legend>
            <label className="check-row">
              <input
                type="radio"
                name={`decision-${finding.finding_id}`}
                checked={decision === "accept"}
                onChange={() => setDecision("accept")}
              />{" "}
              接受处理
            </label>
            <label className="check-row">
              <input
                type="radio"
                name={`decision-${finding.finding_id}`}
                checked={decision === "modify"}
                onChange={() => setDecision("modify")}
              />{" "}
              修改后接受
            </label>
            <label className="check-row">
              <input
                type="radio"
                name={`decision-${finding.finding_id}`}
                checked={decision === "reject"}
                onChange={() => setDecision("reject")}
              />{" "}
              驳回候选项
            </label>
          </fieldset>
          {decision === "modify" && (
            <div className="form-grid">
              <label className="form-field">
                标题
                <input
                  required
                  maxLength={300}
                  value={title}
                  onChange={(event) => setTitle(event.target.value)}
                />
              </label>
              <label className="form-field">
                严重程度
                <select
                  value={severity}
                  onChange={(event) =>
                    setSeverity(event.target.value as Finding["severity"])
                  }
                >
                  <option value="low">低</option>
                  <option value="medium">中</option>
                  <option value="high">高</option>
                  <option value="critical">严重</option>
                </select>
              </label>
              <label className="form-field form-span">
                说明
                <textarea
                  required
                  maxLength={4000}
                  rows={3}
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                />
              </label>
              <label className="form-field form-span">
                建议
                <textarea
                  required
                  maxLength={4000}
                  rows={2}
                  value={recommendation}
                  onChange={(event) => setRecommendation(event.target.value)}
                />
              </label>
            </div>
          )}
          <label className="form-field">
            复核理由
            <textarea
              required
              minLength={1}
              maxLength={2000}
              rows={3}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              aria-describedby={`reason-help-${finding.finding_id}`}
            />
          </label>
          <small id={`reason-help-${finding.finding_id}`}>
            说明核验依据、调整理由或驳回原因。
          </small>
          <div className="modal-actions">
            <Button type="submit" variant="primary" disabled={submitting}>
              {submitting ? "正在提交…" : "保存复核决定"}
            </Button>
          </div>
        </form>
      )}
    </article>
  );
}

function NoFindingConfirmation({
  busy,
  snapshotHash,
  reviewTaskId,
  runId,
  onDone,
  onError,
}: {
  busy: boolean;
  snapshotHash: string;
  reviewTaskId: string;
  runId: string;
  onDone: () => void;
  onError: (value: string) => void;
}) {
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    onError("");
    const scope = `decision:${reviewTaskId}:${runId}:__review_complete__`;
    try {
      await api.decide(
        reviewTaskId,
        runId,
        "__review_complete__",
        {
          decision: "confirm_no_findings",
          expected_snapshot_hash: snapshotHash,
          reason: reason.trim(),
          modified_finding: null,
        },
        intentKey(scope),
      );
      clearIntentKey(scope);
      onDone();
    } catch (error) {
      onError(errorText(error));
    } finally {
      setSaving(false);
    }
  }
  return (
    <form className="decision-form" onSubmit={(event) => void submit(event)}>
      <h3>確認空结果</h3>
      <label className="form-field">
        確認理由
        <textarea
          required
          maxLength={2000}
          value={reason}
          onChange={(event) => setReason(event.target.value)}
        />
      </label>
      <Button type="submit" variant="primary" disabled={saving || busy}>
        {saving ? "正在保存…" : "确认本次无待复核项目"}
      </Button>
    </form>
  );
}

import type { FormEvent } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiError, errorText } from "../api/client";
import {
  api,
  authorizeDocumentExternalProcessing,
  type DocumentRecord,
  type Project,
  type ReviewTask,
} from "../api/operations";
import type { components } from "../api/schema";
import { useAuth } from "../auth";
import {
  Button,
  DataTable,
  Dialog,
  EmptyState,
  Loading,
  Notice,
  PageHeading,
  StatusBadge,
} from "../ui";
import {
  apiEnumLabel,
  clearIntentKey,
  formatBytes,
  formatDate,
  intentKey,
  REVIEW_TIMEOUT_NOTICE,
} from "../utils";
import { ProjectFormDialog } from "./projects";

type ContextFields = components["schemas"]["ContextFields"];
type ContextData = components["schemas"]["DocumentContext"];
type DocumentSections = components["schemas"]["DocumentSections"];

const processingStates = new Set(["quarantined", "accepted", "parsing"]);

// The per-file confirmation control only exists in the build that actually talks to the
// real supplier; offline builds never show it. Read at render time (not into a module
// constant) so a test can exercise exactly the build it claims to cover.
function externalAuthorizationEnabled(): boolean {
  return import.meta.env.VITE_REVIEW_MODE === "dec007-real-qwen";
}

const fragmentSourceLabels: Record<string, string> = {
  native: "解析原文",
  ocr: "OCR 识别",
  manual: "人工转录",
};

const issueLabels: Record<string, string> = {
  TYPE_MISMATCH: "文件类型与内容不匹配",
  SIZE_LIMIT: "文件超过大小限制",
  MALICIOUS_CONTENT: "安全扫描发现风险内容",
  ARCHIVE_LIMIT: "压缩包内容超过限制",
  INVALID_FILE: "文件无法识别",
  ENCRYPTED_FILE: "文件已加密，无法处理",
  PAGE_LIMIT: "页数超过处理限制",
  IMAGE_LIMIT: "图像数量超过处理限制",
  TEXT_LIMIT: "解析文本超过处理限制",
  OCR_LIMIT: "OCR 处理超过限制",
  LOW_QUALITY: "解析质量不足，需要人工检查",
  SCANNER_UNAVAILABLE: "安全扫描服务不可用",
  SCANNER_STALE: "安全扫描结果已过期",
  PARSE_TIMEOUT: "文档解析超时",
  PARSE_FAILED: "文档解析失败",
  HASH_MISMATCH: "文件完整性校验失败",
  ACTOR_FORBIDDEN: "当前账号没有文件操作权限",
  OUTPUT_LIMIT: "解析结果超过大小限制",
};

export function ProjectPage() {
  const { projectId = "" } = useParams();
  const { identity } = useAuth();
  const navigate = useNavigate();
  const [project, setProject] = useState<Project | null>(null);
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [reviews, setReviews] = useState<ReviewTask[]>([]);
  const [versions, setVersions] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [selected, setSelected] = useState<string[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [startingReview, setStartingReview] = useState(false);
  const [showProjectEdit, setShowProjectEdit] = useState(false);
  const [contextDocument, setContextDocument] = useState<DocumentRecord | null>(
    null,
  );
  const [correctionDocument, setCorrectionDocument] =
    useState<DocumentRecord | null>(null);
  const [authorizationDocument, setAuthorizationDocument] =
    useState<DocumentRecord | null>(null);

  const reload = useCallback(() => setRefresh((value) => value + 1), []);

  // biome-ignore lint/correctness/useExhaustiveDependencies: refresh intentionally reloads server state after a user mutation.
  useEffect(() => {
    if (!projectId) return;
    let active = true;
    let timer: number | undefined;
    const controller = new AbortController();
    const load = async () => {
      try {
        const [
          projectResponse,
          documentResponse,
          reviewResponse,
          versionResponse,
        ] = await Promise.all([
          api.project(projectId, { signal: controller.signal }),
          api.documents(projectId, 0, 100, { signal: controller.signal }),
          api.reviews(projectId, 0, 50, { signal: controller.signal }),
          api.projectVersions(projectId, { signal: controller.signal }),
        ]);
        if (!active) return;
        setProject(projectResponse);
        setDocuments(documentResponse.items);
        setReviews(reviewResponse.items);
        setVersions(versionResponse.items);
        setSelected((current) =>
          current.filter((id) =>
            documentResponse.items.some(
              (item) => item.document_id === id && item.status === "ready",
            ),
          ),
        );
        setError(null);
        setLoading(false);
        const needsRefresh =
          documentResponse.items.some((item) =>
            processingStates.has(item.status),
          ) ||
          reviewResponse.items.some(
            (item) => item.status === "queued" || item.status === "running",
          );
        if (needsRefresh) timer = window.setTimeout(load, 3500);
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
  }, [projectId, refresh]);

  const selectedReady = useMemo(
    () =>
      documents.filter(
        (item) =>
          item.status === "ready" && selected.includes(item.document_id),
      ),
    [documents, selected],
  );

  // A document the quality gate flagged cannot be selected at all; the page says so and
  // points at the only server-supported repair path instead of leaving a dead end.
  const unrepairedCount = useMemo(
    () => documents.filter((item) => item.status === "needs_review").length,
    [documents],
  );

  function toggleSelected(document: DocumentRecord) {
    if (document.status !== "ready") return;
    setSelected((current) =>
      current.includes(document.document_id)
        ? current.filter((id) => id !== document.document_id)
        : [...current, document.document_id],
    );
  }

  async function uploadFile() {
    if (!file || !project) return;
    setUploading(true);
    setError(null);
    setNotice(null);
    const keyScope = `upload:${project.project_id}`;
    try {
      const result = await api.upload(
        project.project_id,
        file,
        intentKey(keyScope),
      );
      clearIntentKey(keyScope);
      setNotice(
        `文件已接收。服务端当前状态：${apiEnumLabel(result.status)}。接收成功不代表解析完成。`,
      );
      setFile(null);
      const picker = document.getElementById(
        "tender-file",
      ) as HTMLInputElement | null;
      if (picker) picker.value = "";
      reload();
    } catch (reason) {
      if (reason instanceof ApiError && [413, 415, 422].includes(reason.status))
        clearIntentKey(keyScope);
      setError(errorText(reason));
    } finally {
      setUploading(false);
    }
  }

  async function startReview() {
    if (!project || selectedReady.length === 0) return;
    setStartingReview(true);
    setError(null);
    setNotice(null);
    const keyScope = `review:${project.project_id}`;
    try {
      const task = await api.createReview(
        project.project_id,
        selectedReady.map((item) => item.document_id),
        intentKey(keyScope),
      );
      clearIntentKey(keyScope);
      setSelected([]);
      setNotice(
        `审查任务 ${task.review_task_id} 已由服务端接收，当前状态：${apiEnumLabel(task.status)}。`,
      );
      reload();
      if (
        task.status === "waiting_human" ||
        task.status === "result_published"
      ) {
        navigate(
          `/reviews/${encodeURIComponent(task.review_task_id)}/${encodeURIComponent(task.run_id)}`,
        );
      }
    } catch (reason) {
      if (reason instanceof DOMException && reason.name === "AbortError") {
        // The 120 s client abort is not a lost task: reload the persisted task list and
        // say so instead of only showing a generic "cancelled or timed out" message.
        setError(null);
        setNotice(REVIEW_TIMEOUT_NOTICE);
        reload();
      } else if (reason instanceof ApiError && reason.status === 403) {
        // In a build with per-file external processing the server refuses a run whose
        // document has not been confirmed; the shared 403 message alone would hide that.
        setError(
          `${errorText(reason)}真实模型部署还要求所选文件已逐个登记外发授权；` +
            "请先在文档行完成「登记外发授权」，或取消选择未登记的文件后重试。",
        );
      } else {
        setError(errorText(reason));
      }
    } finally {
      setStartingReview(false);
    }
  }

  if (loading) return <Loading label="正在读取项目与文档状态" />;
  if (!project) {
    return (
      <section className="page-wrap">
        <Notice kind="error">{error || "项目不存在或当前账号不可见。"}</Notice>
        <Link className="button button-secondary" to="/projects">
          返回项目列表
        </Link>
      </section>
    );
  }

  return (
    <section className="page-wrap">
      <PageHeading
        eyebrow="项目工作台"
        title={project.name}
        description={`${project.region} · ${apiEnumLabel(project.procurement_type)} · ${apiEnumLabel(project.project_type)}`}
        actions={
          identity?.role === "reviewer" ? (
            <Button onClick={() => setShowProjectEdit(true)}>
              编辑项目上下文
            </Button>
          ) : undefined
        }
      />
      {error && <Notice kind="error">{error}</Notice>}
      {notice && <Notice kind="success">{notice}</Notice>}
      <div className="summary-grid">
        <div className="summary-card">
          <span>项目版本</span>
          <strong>v{project.version}</strong>
          <small>上下文采用乐观版本控制</small>
        </div>
        <div className="summary-card">
          <span>文档记录</span>
          <strong>{documents.length}</strong>
          <small>来自项目文档列表 API</small>
        </div>
        <div className="summary-card">
          <span>审查任务</span>
          <strong>{reviews.length}</strong>
          <small>来自持久任务状态 API</small>
        </div>
        <div className="summary-card">
          <span>预算金额</span>
          <strong>
            {project.budget_amount == null
              ? "未提供"
              : `${new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 }).format(project.budget_amount)} 元`}
          </strong>
          <small>项目上下文版本 v{project.version}</small>
        </div>
      </div>

      <section className="panel" aria-labelledby="documents-heading">
        <div className="section-heading section-heading-wrap">
          <div>
            <h2 id="documents-heading">招标文件</h2>
            <p className="muted">
              上传后按服务端扫描、解析、质量与上下文状态展示。
            </p>
          </div>
          {identity?.role === "reviewer" && (
            <div className="upload-controls">
              <label className="file-picker" htmlFor="tender-file">
                选择 PDF、DOCX 或扫描件
              </label>
              <input
                id="tender-file"
                type="file"
                accept=".pdf,.docx,.png,.jpg,.jpeg,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,image/png,image/jpeg"
                onChange={(event) => setFile(event.target.files?.[0] || null)}
              />
              {file && (
                <span className="selected-file" title={file.name}>
                  {file.name} · {formatBytes(file.size)}
                </span>
              )}
              <Button
                variant="primary"
                disabled={!file || uploading}
                onClick={() => void uploadFile()}
              >
                {uploading ? "正在安全接收…" : "上传文件"}
              </Button>
            </div>
          )}
        </div>
        {documents.length === 0 ? (
          <EmptyState
            title="尚未上传文档"
            description="上传文件后，系统会显示真实扫描、解析和质量状态。"
          />
        ) : (
          <DataTable label="项目招标文件列表">
            <thead>
              <tr>
                <th scope="col">审查选择</th>
                <th scope="col">文档</th>
                <th scope="col">处理状态</th>
                <th scope="col">解析版本</th>
                <th scope="col">上下文版本</th>
                <th scope="col">文件校验</th>
                <th scope="col">操作</th>
              </tr>
            </thead>
            <tbody>
              {documents.map((doc) => (
                <tr key={doc.document_id}>
                  <td>
                    <input
                      aria-label={`选择文档 ${doc.document_id} 开始审查`}
                      type="checkbox"
                      disabled={
                        identity?.role !== "reviewer" || doc.status !== "ready"
                      }
                      checked={selected.includes(doc.document_id)}
                      onChange={() => toggleSelected(doc)}
                    />
                  </td>
                  <td>
                    <strong>招标文件</strong>
                    <small className="table-sub">
                      {doc.document_id} · {doc.file_format.toUpperCase()} ·{" "}
                      {formatBytes(doc.size_bytes)}
                    </small>
                    {(doc.issues?.length ?? 0) > 0 && (
                      <small className="issue-list">
                        {doc.issues
                          ?.map(
                            (issue) =>
                              issueLabels[issue] || "需要处理的文档问题",
                          )
                          .join("；")}
                      </small>
                    )}
                  </td>
                  <td>
                    <StatusBadge status={doc.status} />
                  </td>
                  <td>
                    {doc.parse_version > 0
                      ? `P${doc.parse_version}`
                      : "尚未解析"}
                  </td>
                  <td>
                    {doc.context_version > 0
                      ? `C${doc.context_version}`
                      : "尚未确认"}
                  </td>
                  <td>
                    <code className="hash-short">
                      SHA-256 {doc.sha256.slice(0, 12)}…
                    </code>
                  </td>
                  <td>
                    <Button
                      variant="quiet"
                      onClick={() => setContextDocument(doc)}
                    >
                      查看上下文
                    </Button>
                    {identity?.role === "reviewer" &&
                      doc.status === "needs_review" && (
                        <Button
                          variant="quiet"
                          onClick={() => setCorrectionDocument(doc)}
                        >
                          查看/校正文本
                        </Button>
                      )}
                    {externalAuthorizationEnabled() &&
                      identity?.role === "reviewer" && (
                        <Button
                          variant="quiet"
                          onClick={() => setAuthorizationDocument(doc)}
                        >
                          登记外发授权
                        </Button>
                      )}
                  </td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        )}
        {identity?.role === "reviewer" && (
          <div className="review-start-row">
            <span className="muted">
              只能选择服务端状态为“可用于审查”的文档。当前选中{" "}
              {selectedReady.length} 份。
              {unrepairedCount > 0 &&
                `另有 ${unrepairedCount} 份文档解析质量不足（需人工校对），请先「查看/校正文本」按原件转录，再确认上下文。`}
            </span>
            <Button
              variant="primary"
              disabled={!selectedReady.length || startingReview}
              onClick={() => void startReview()}
            >
              {startingReview ? "正在请求审查…" : "发起审查"}
            </Button>
          </div>
        )}
      </section>

      <section className="panel" aria-labelledby="review-tasks-heading">
        <div className="section-heading">
          <h2 id="review-tasks-heading">审查任务</h2>
          <span className="muted">刷新页面后将从服务端恢复</span>
        </div>
        {reviews.length === 0 ? (
          <p className="empty-inline">暂无持久化审查任务。</p>
        ) : (
          <DataTable label="项目审查任务列表">
            <thead>
              <tr>
                <th scope="col">任务编号</th>
                <th scope="col">执行批次</th>
                <th scope="col">状态</th>
                <th scope="col">结果版本</th>
                <th scope="col">操作</th>
              </tr>
            </thead>
            <tbody>
              {reviews.map((review) => (
                <tr key={`${review.review_task_id}-${review.run_id}`}>
                  <td>
                    <code>{review.review_task_id}</code>
                  </td>
                  <td>
                    <code>{review.run_id}</code>
                  </td>
                  <td>
                    <StatusBadge status={review.status} />
                  </td>
                  <td>
                    {review.result_id ? (
                      <code>{review.result_id}</code>
                    ) : (
                      "尚未发布"
                    )}
                  </td>
                  <td>
                    <Link
                      className="table-link"
                      to={`/reviews/${encodeURIComponent(review.review_task_id)}/${encodeURIComponent(review.run_id)}`}
                    >
                      打开任务
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        )}
      </section>

      <section className="panel" aria-labelledby="versions-heading">
        <div className="section-heading">
          <h2 id="versions-heading">项目版本记录</h2>
          <span className="muted">只读历史快照</span>
        </div>
        <DataTable label="项目版本记录">
          <thead>
            <tr>
              <th scope="col">版本</th>
              <th scope="col">项目名称</th>
              <th scope="col">地区</th>
              <th scope="col">项目类型</th>
              <th scope="col">记录时间</th>
            </tr>
          </thead>
          <tbody>
            {versions.map((version) => (
              <tr key={version.version}>
                <td>v{version.version}</td>
                <td>{version.name}</td>
                <td>{version.region}</td>
                <td>{apiEnumLabel(version.project_type)}</td>
                <td>{formatDate(version.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </DataTable>
      </section>

      <ProjectFormDialog
        open={showProjectEdit}
        title="编辑项目上下文"
        initial={project}
        onClose={() => setShowProjectEdit(false)}
        onSaved={(saved) => {
          setProject(saved);
          setShowProjectEdit(false);
          reload();
        }}
      />
      <ContextDialog
        document={contextDocument}
        project={project}
        canEdit={identity?.role === "reviewer"}
        onClose={() => setContextDocument(null)}
        onSaved={() => {
          setContextDocument(null);
          reload();
        }}
      />
      <TextCorrectionDialog
        key={`correction-${correctionDocument?.document_id ?? "none"}`}
        document={correctionDocument}
        onClose={() => setCorrectionDocument(null)}
        onSubmitted={(message, repaired, keepOpen) => {
          setNotice(message);
          reload();
          if (!keepOpen) setCorrectionDocument(null);
          // A correction that re-passed the gate leaves exactly one step: the reviewer
          // confirms the context, which is what turns the document into "ready".
          if (repaired && repaired.status === "needs_confirmation") {
            setCorrectionDocument(null);
            setContextDocument(repaired);
          }
        }}
      />
      <ExternalAuthorizationDialog
        key={`authorization-${authorizationDocument?.document_id ?? "none"}`}
        document={authorizationDocument}
        onClose={() => setAuthorizationDocument(null)}
        onSaved={(message) => {
          setAuthorizationDocument(null);
          setNotice(message);
          reload();
        }}
      />
    </section>
  );
}

const EXTERNAL_AUTHORIZATION_STATEMENT =
  "我确认我依法有权处理该文件，并同意把审查所需的必要内容（经脱敏最小化的原文分段）交由阿里云百炼（bailian）处理。";

function ExternalAuthorizationDialog({
  document,
  onClose,
  onSaved,
}: {
  document: DocumentRecord | null;
  onClose: () => void;
  onSaved: (message: string) => void;
}) {
  const [confirmed, setConfirmed] = useState(false);
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (!document || !confirmed || !reason.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const record = await authorizeDocumentExternalProcessing(
        document.project_id,
        document.document_id,
        { reason: reason.trim(), confirmed: true },
      );
      onSaved(
        `已登记外发授权：文件 ${record.document_id}（SHA-256 ${record.sha256.slice(0, 12)}…），` +
          `操作人 ${record.approved_by}，时间 ${record.approved_at}。该授权只对本文件生效，可被运维收回。`,
      );
    } catch (reasonValue) {
      setError(errorText(reasonValue));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog
      open={document !== null}
      title="登记该文件的外发处理授权"
      onClose={onClose}
      size="wide"
    >
      {error && <Notice kind="error">{error}</Notice>}
      {document && (
        <div className="context-layout">
          <div className="context-doc-summary">
            <strong>{document.document_id}</strong>
            <span>
              文件 SHA-256：<code>{document.sha256}</code>
            </span>
            <span>
              <StatusBadge status={document.status} />
            </span>
          </div>
          <Notice kind="info">
            {EXTERNAL_AUTHORIZATION_STATEMENT}
            该确认只对上面这一个文件的 SHA-256 生效，不会放行其他文件，
            也不会放宽额度或覆盖“未核验法规不得作为违法依据”的证据规则。
          </Notice>
          <form
            className="form-grid"
            onSubmit={(event) => {
              event.preventDefault();
              void submit();
            }}
          >
            <div className="form-field form-span">
              <label htmlFor="external-authorization-reason">
                授权理由 <span className="required-mark">*</span>
              </label>
              <textarea
                id="external-authorization-reason"
                rows={2}
                minLength={1}
                maxLength={500}
                required
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                aria-describedby="external-authorization-reason-hint"
              />
              <small id="external-authorization-reason-hint">
                将写入追加式审计记录（文件哈希、文件标识、理由、时间、操作人）。
              </small>
            </div>
            <div className="form-field form-span">
              <label htmlFor="external-authorization-confirm">
                <input
                  id="external-authorization-confirm"
                  type="checkbox"
                  checked={confirmed}
                  onChange={(event) => setConfirmed(event.target.checked)}
                />{" "}
                我已阅读并同意上述声明（服务端同样校验该确认）
              </label>
            </div>
            <div className="modal-actions form-span">
              <Button type="button" onClick={onClose}>
                取消
              </Button>
              <Button
                type="submit"
                variant="primary"
                disabled={saving || !confirmed || !reason.trim()}
              >
                {saving ? "正在登记…" : "确认授权该文件"}
              </Button>
            </div>
          </form>
        </div>
      )}
    </Dialog>
  );
}

function TextCorrectionDialog({
  document,
  onClose,
  onSubmitted,
}: {
  document: DocumentRecord | null;
  onClose: () => void;
  onSubmitted: (
    message: string,
    repaired: DocumentRecord | null,
    keepOpen: boolean,
  ) => void;
}) {
  const [sections, setSections] = useState<DocumentSections | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [reason, setReason] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fetches, setFetches] = useState(0);

  // biome-ignore lint/correctness/useExhaustiveDependencies: fetches re-reads the server-side fragments after a conflict or a correction that still fails the gate.
  useEffect(() => {
    if (!document) return;
    let active = true;
    setLoading(true);
    setError(null);
    setSections(null);
    api
      .documentSections(document.project_id, document.document_id)
      .then((value) => {
        if (!active) return;
        setSections(value);
        setDrafts(
          Object.fromEntries(
            value.items.map((item) => [item.section_id, item.effective.text]),
          ),
        );
      })
      .catch((reasonValue: unknown) => {
        if (active) setError(errorText(reasonValue));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [document, fetches]);

  const changed = (sections?.items ?? []).filter(
    (item) =>
      (drafts[item.section_id] ?? item.effective.text) !== item.effective.text,
  );
  const blank = changed.some((item) => !(drafts[item.section_id] ?? "").trim());

  async function submit() {
    if (!document || !sections) return;
    if (changed.length === 0) {
      setError("尚未修改任何片段文本。请按原件转录有问题的片段后再提交。");
      return;
    }
    if (blank) {
      setError("片段文本不能为空。请按原件填写后再提交。");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const repaired = await api.correctDocumentText(
        document.project_id,
        document.document_id,
        {
          expected_parse_version: sections.parse_version,
          reason: reason.trim(),
          corrections: changed.map((item) => ({
            section_id: item.section_id,
            text: drafts[item.section_id] ?? item.effective.text,
          })),
        },
      );
      if (repaired.status === "needs_confirmation") {
        onSubmitted(
          `文本校正已记录（解析版本 P${repaired.parse_version}），服务端质量门禁已通过。` +
            "请继续确认上下文；完成后该文档才可勾选发起审查。",
          repaired,
          false,
        );
        return;
      }
      onSubmitted(
        `文本校正已记录（解析版本 P${repaired.parse_version}），但服务端质量门禁仍未通过。` +
          "请继续按原件转录仍然质量不足的片段；只有服务端重新判定通过后才会进入上下文确认。",
        null,
        true,
      );
      setFetches((value) => value + 1);
    } catch (reasonValue) {
      setError(errorText(reasonValue));
      if (reasonValue instanceof ApiError && reasonValue.status === 409) {
        // Another tab corrected the same document: re-read instead of guessing.
        setFetches((value) => value + 1);
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog
      open={document !== null}
      title="查看与校正解析文本"
      onClose={onClose}
      size="wide"
    >
      {loading && <Loading label="正在读取服务端解析片段" />}
      {error && <Notice kind="error">{error}</Notice>}
      {document && (
        <div className="context-layout">
          <div className="context-doc-summary">
            <strong>{document.document_id}</strong>
            <span>
              <StatusBadge status={document.status} />
            </span>
            <span>
              解析版本 P{document.parse_version} · 上下文版本 C
              {document.context_version}
            </span>
            <span>
              文件 SHA-256：<code>{document.sha256.slice(0, 16)}…</code>
            </span>
          </div>
          <Notice kind="info">
            解析质量不足时，只有按原件人工转录才能让这份文件通过服务端质量门禁。
            校正会写入可审计的修订记录，自动解析原文与文件哈希保持不变，
            是否达标仍由服务端重新判定；请勿填写未经核对的内容。
          </Notice>
          {sections && (
            <form
              className="form-grid"
              onSubmit={(event) => {
                event.preventDefault();
                void submit();
              }}
            >
              <p className="muted form-span">
                服务端解析版本 P{sections.parse_version}，共{" "}
                {sections.items.length} 个片段。只提交发生修改的片段（当前{" "}
                {changed.length} 处）。
              </p>
              {sections.items.map((item, index) => (
                <div className="form-field form-span" key={item.section_id}>
                  <label htmlFor={`correction-${item.section_id}`}>
                    片段 {index + 1} ·{" "}
                    {fragmentSourceLabels[item.effective.source] ||
                      item.effective.source}{" "}
                    · 修订 r{item.revision}
                  </label>
                  <small>
                    定位 <code>{item.effective.locator}</code>
                    {!item.effective.text.trim() &&
                      " · 服务端未得到文字，需按原件转录"}
                  </small>
                  <textarea
                    id={`correction-${item.section_id}`}
                    rows={3}
                    maxLength={8000}
                    value={drafts[item.section_id] ?? item.effective.text}
                    onChange={(event) =>
                      setDrafts((current) => ({
                        ...current,
                        [item.section_id]: event.target.value,
                      }))
                    }
                    aria-describedby={`correction-${item.section_id}-automatic`}
                  />
                  <small id={`correction-${item.section_id}-automatic`}>
                    自动解析原文：
                    {item.automatic.text.trim()
                      ? item.automatic.text
                      : "（空）"}
                  </small>
                </div>
              ))}
              <div className="form-field form-span">
                <label htmlFor="correction-reason">
                  校正理由 <span className="required-mark">*</span>
                </label>
                <textarea
                  id="correction-reason"
                  rows={2}
                  minLength={1}
                  maxLength={1000}
                  required
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  aria-describedby="correction-reason-hint"
                />
                <small id="correction-reason-hint">
                  将随每个片段的修订写入可审计记录（操作人、时间、理由）。
                </small>
              </div>
              <div className="modal-actions form-span">
                <Button type="button" onClick={onClose}>
                  关闭
                </Button>
                <Button
                  type="submit"
                  variant="primary"
                  disabled={
                    saving ||
                    loading ||
                    changed.length === 0 ||
                    blank ||
                    !reason.trim()
                  }
                >
                  {saving ? "正在提交校正…" : `提交 ${changed.length} 处校正`}
                </Button>
              </div>
            </form>
          )}
        </div>
      )}
    </Dialog>
  );
}

function ContextDialog({
  document,
  project,
  canEdit,
  onClose,
  onSaved,
}: {
  document: DocumentRecord | null;
  project: Project;
  canEdit: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [data, setData] = useState<ContextData | null>(null);
  const [fields, setFields] = useState<ContextFields | null>(null);
  const [reason, setReason] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!document) return;
    let active = true;
    setData(null);
    setFields(null);
    setError(null);
    setLoading(true);
    api
      .documentContext(document.project_id, document.document_id)
      .then((context) => {
        if (!active) return;
        setData(context);
        const value = (field: ContextData["candidates"][number]["field"]) =>
          context.candidates.find((item) => item.field === field)?.value;
        const manual = context.manual;
        const validChoice = <T extends string>(
          candidate: string | null | undefined,
          allowed: readonly T[],
          fallback: T,
        ): T =>
          candidate && allowed.includes(candidate as T)
            ? (candidate as T)
            : fallback;
        setFields(
          manual || {
            name: value("name") || project.name,
            procurement_type: validChoice(
              value("procurement_type"),
              ["government", "enterprise", "other"],
              project.procurement_type,
            ),
            project_type: validChoice(
              value("project_type"),
              ["works", "goods", "services"],
              project.project_type,
            ),
            region: value("region") || project.region,
            industry: value("industry") ?? project.industry ?? null,
            budget_amount: value("budget_amount")
              ? Number(value("budget_amount"))
              : (project.budget_amount ?? null),
            applicable_system:
              value("applicable_system") ?? project.applicable_system ?? null,
            procurement_method: project.procurement_method,
            buyer_type: project.buyer_type,
            subject_type: project.subject_type,
            legal_frameworks: project.legal_frameworks ?? [],
          },
        );
      })
      .catch((reason: unknown) => active && setError(errorText(reason)))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [document, project]);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!document || !data || !fields) return;
    setSaving(true);
    setError(null);
    try {
      await api.confirmDocumentContext(
        document.project_id,
        document.document_id,
        {
          expected_version: data.version,
          reason: reason.trim(),
          context: fields,
        },
      );
      onSaved();
    } catch (reasonValue) {
      setError(errorText(reasonValue));
    } finally {
      setSaving(false);
    }
  }

  function update<K extends keyof ContextFields>(
    key: K,
    value: ContextFields[K],
  ) {
    setFields((current) => (current ? { ...current, [key]: value } : current));
  }

  return (
    <Dialog
      open={document !== null}
      title="文档上下文与处理记录"
      onClose={onClose}
      size="wide"
    >
      {loading && <Loading label="正在读取服务端上下文" />}
      {error && <Notice kind="error">{error}</Notice>}
      {document && (
        <div className="context-layout">
          <div className="context-doc-summary">
            <strong>{document.document_id}</strong>
            <span>
              <StatusBadge status={document.status} />
            </span>
            <span>
              文件 SHA-256：<code>{document.sha256}</code>
            </span>
            <span>
              解析版本 P{document.parse_version} · 上下文版本 C
              {document.context_version}
            </span>
            {(document.issues?.length ?? 0) > 0 && (
              <Notice kind="info">
                {document.issues
                  ?.map((issue) => issueLabels[issue] || "文档处理提示")
                  .join("；")}
              </Notice>
            )}
          </div>
          {data && (
            <div className="candidate-panel">
              <h3>解析得到的上下文候选</h3>
              {data.candidates.length === 0 ? (
                <p className="muted">
                  服务端未返回上下文候选。请按项目正式资料核对后填写。
                </p>
              ) : (
                <ul className="candidate-list">
                  {data.candidates.map((candidate, index) => (
                    <li
                      key={`${candidate.field}-${candidate.section_id || index}`}
                    >
                      <span>{apiEnumLabel(candidate.field)}</span>
                      <strong>{candidate.value ?? "未识别"}</strong>
                      <small>
                        置信度 {Math.round(candidate.confidence * 100)}%
                        {candidate.section_id
                          ? ` · 片段 ${candidate.section_id}`
                          : ""}
                      </small>
                    </li>
                  ))}
                </ul>
              )}
              <p className="muted">
                候选值来自服务端解析，不会自动视为已确认。保存后将生成新的上下文版本。
              </p>
            </div>
          )}
          {canEdit &&
          fields &&
          (document.status === "needs_confirmation" ||
            document.status === "ready") ? (
            <form className="form-grid" onSubmit={(event) => void save(event)}>
              <div className="form-span">
                <h3>审核并确认上下文</h3>
              </div>
              <ContextInput
                label="项目名称"
                value={fields.name}
                onChange={(value) => update("name", value)}
              />
              <div className="form-field">
                <label htmlFor="context-procurement">采购类型</label>
                <select
                  id="context-procurement"
                  value={fields.procurement_type}
                  onChange={(event) =>
                    update(
                      "procurement_type",
                      event.target.value as ContextFields["procurement_type"],
                    )
                  }
                >
                  <option value="government">政府采购</option>
                  <option value="enterprise">企业采购</option>
                  <option value="other">其他</option>
                </select>
              </div>
              <div className="form-field">
                <label htmlFor="context-project-type">项目类型</label>
                <select
                  id="context-project-type"
                  value={fields.project_type}
                  onChange={(event) =>
                    update(
                      "project_type",
                      event.target.value as ContextFields["project_type"],
                    )
                  }
                >
                  <option value="works">工程</option>
                  <option value="goods">货物</option>
                  <option value="services">服务</option>
                </select>
              </div>
              <ContextInput
                label="地区"
                value={fields.region}
                onChange={(value) => update("region", value)}
              />
              <ContextInput
                label="行业"
                value={fields.industry || ""}
                required={false}
                onChange={(value) => update("industry", value || null)}
              />
              <div className="form-field">
                <label htmlFor="context-budget">预算金额（元）</label>
                <input
                  id="context-budget"
                  type="number"
                  min="0"
                  step="0.01"
                  value={fields.budget_amount ?? ""}
                  onChange={(event) =>
                    update(
                      "budget_amount",
                      event.target.value ? Number(event.target.value) : null,
                    )
                  }
                />
              </div>
              <div className="form-field form-span">
                <label htmlFor="context-system">适用制度说明</label>
                <textarea
                  id="context-system"
                  rows={2}
                  value={fields.applicable_system || ""}
                  onChange={(event) =>
                    update("applicable_system", event.target.value || null)
                  }
                />
              </div>
              <div className="form-field form-span">
                <label htmlFor="context-reason">
                  确认理由 <span className="required-mark">*</span>
                </label>
                <textarea
                  id="context-reason"
                  rows={2}
                  minLength={1}
                  maxLength={1000}
                  required
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  aria-describedby="context-reason-hint"
                />
                <small id="context-reason-hint">
                  请说明核对来源或需要修正的内容。
                </small>
              </div>
              <div className="modal-actions form-span">
                <Button type="button" onClick={onClose}>
                  关闭
                </Button>
                <Button
                  type="submit"
                  variant="primary"
                  disabled={saving || loading}
                >
                  {saving ? "正在保存…" : "确认上下文"}
                </Button>
              </div>
            </form>
          ) : !canEdit ? (
            <p className="muted">
              当前账号仅有读取权限，项目上下文修改由审核员操作。
            </p>
          ) : (
            <p className="muted">
              当前处理状态不允许确认上下文。请根据页面显示的质量或安全状态处理后再试。
            </p>
          )}
        </div>
      )}
    </Dialog>
  );
}

function ContextInput({
  label,
  value,
  onChange,
  required = true,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  required?: boolean;
}) {
  const id = `context-${label}`;
  return (
    <div className="form-field">
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        required={required}
        maxLength={300}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </div>
  );
}

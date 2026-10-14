import { useCallback, useEffect, useMemo, useState } from "react";
import { errorText } from "../api/client";
import {
  api,
  type ConfigurationCatalog,
  type ConfigurationState,
  type LegalManagement,
} from "../api/operations";
import type { components } from "../api/schema";
import { useAuth } from "../auth";
import { Button, Loading, Notice, PageHeading } from "../ui";

type Policy = components["schemas"]["ModelPolicySnapshot"];
type SkillId = components["schemas"]["SkillCatalogItem"]["skill_id"];

function requestId() {
  return crypto.randomUUID();
}

export function ConfigurationPage() {
  const { identity } = useAuth();
  const [catalog, setCatalog] = useState<ConfigurationCatalog | null>(null);
  const [config, setConfig] = useState<ConfigurationState | null>(null);
  const [legal, setLegal] = useState<LegalManagement | null>(null);
  const [selectedSkills, setSelectedSkills] = useState<SkillId[]>([]);
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [configReason, setConfigReason] = useState("");
  const [legalReason, setLegalReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async (signal?: AbortSignal) => {
    const [nextCatalog, nextConfig, nextLegal] = await Promise.all([
      api.configurationCatalog({ signal }),
      api.configurations({ signal }),
      api.legalManagement({ signal }),
    ]);
    setCatalog(nextCatalog);
    setConfig(nextConfig);
    setLegal(nextLegal);
    const active = nextConfig.items.find((item) => item.status === "active");
    const source = active?.snapshot.model_policy ?? nextCatalog.model_policy;
    setPolicy(source as Policy);
    setSelectedSkills(
      (active?.snapshot.skill_ids as SkillId[] | undefined) ??
        nextCatalog.skills.map((item) => item.skill_id),
    );
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void reload(controller.signal)
      .catch((reason: unknown) => setError(errorText(reason)))
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [reload]);

  const activeConfig = useMemo(
    () => config?.items.find((item) => item.status === "active") ?? null,
    [config],
  );
  const draftConfig = useMemo(
    () => config?.items.find((item) => item.status === "draft") ?? null,
    [config],
  );
  const rollbackConfig = useMemo(() => {
    const publishedIds = new Set(
      config?.events
        .filter(
          (event) =>
            event.operation === "publish" || event.operation === "rollback",
        )
        .map((event) => event.revision_id)
        .filter((id): id is string => Boolean(id)),
    );
    return (
      config?.items.find(
        (item) =>
          item.status === "inactive" && publishedIds.has(item.revision_id),
      ) ?? null
    );
  }, [config]);
  const activeLegalMismatch = Boolean(
    activeConfig &&
      legal?.publication_id &&
      activeConfig.snapshot.legal_publication_id !== legal.publication_id,
  );
  const legalDraft = legal?.revisions.find(
    (item) => item.revision_id === legal.draft_revision_id,
  );
  const legalRollback = legal?.publications.find(
    (item) => item.publication_id !== legal.publication_id && item.revision_id,
  );

  async function perform(label: string, action: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await action();
      await reload();
      setMessage(label);
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(false);
    }
  }

  function createConfigDraft() {
    if (!config || !legal?.publication_id || !policy) return;
    const reason = configReason.trim();
    if (!reason) {
      setError("请填写本次审查配置变更原因。");
      return;
    }
    void perform("审查配置草稿已保存。", () =>
      api.createConfigurationDraft({
        request_id: requestId(),
        expected_sequence: config.sequence,
        expected_draft_sequence: config.draft_sequence,
        expected_legal_publication_id: legal.publication_id as string,
        skill_ids: selectedSkills,
        model_policy: policy,
        reason,
      }),
    );
  }

  function publishConfigDraft() {
    if (!config || !draftConfig) return;
    const reason = configReason.trim();
    if (!reason) {
      setError("请填写发布原因。");
      return;
    }
    void perform("审查配置已发布，新任务将使用此版本。", () =>
      api.publishConfiguration({
        request_id: requestId(),
        expected_sequence: config.sequence,
        revision_id: draftConfig.revision_id,
        reason,
      }),
    );
  }

  function deactivateConfig() {
    if (!config) return;
    const reason = configReason.trim();
    if (!reason) {
      setError("请填写停用原因。");
      return;
    }
    void perform("审查配置已停用。", () =>
      api.deactivateConfiguration({
        request_id: requestId(),
        expected_sequence: config.sequence,
        reason,
      }),
    );
  }

  function rollbackConfigRelease() {
    if (!config || !rollbackConfig) return;
    const reason = configReason.trim();
    if (!reason) {
      setError("请填写回滚原因。");
      return;
    }
    void perform("审查配置已回滚到所选历史版本。", () =>
      api.rollbackConfiguration({
        request_id: requestId(),
        expected_sequence: config.sequence,
        target_revision_id: rollbackConfig.revision_id,
        reason,
      }),
    );
  }

  function createLegalDraft() {
    if (!legal) return;
    const reason = legalReason.trim();
    if (!reason) {
      setError("请填写法规版本草稿说明。");
      return;
    }
    void perform("法规修订草稿已保存。", () =>
      api.createLegalDraft({
        request_id: requestId(),
        expected_draft_sequence: legal.draft_sequence,
        reason,
      }),
    );
  }

  function publishLegalDraft() {
    if (!legal || !legalDraft) return;
    const reason = legalReason.trim();
    if (!reason) {
      setError("请填写法规发布原因。");
      return;
    }
    void perform("法规版本已发布；新审查配置需要重新绑定法规发布号。", () =>
      api.changeLegalPublication({
        request_id: requestId(),
        expected_sequence: legal.sequence,
        expected_draft_sequence: legal.draft_sequence,
        operation: "publish",
        revision_id: legalDraft.revision_id,
        reason,
      }),
    );
  }

  function deactivateLegal() {
    if (!legal) return;
    const reason = legalReason.trim();
    if (!reason) {
      setError("请填写法规停用原因。");
      return;
    }
    void perform("法规发布已停用。", () =>
      api.changeLegalPublication({
        request_id: requestId(),
        expected_sequence: legal.sequence,
        operation: "disable",
        reason,
      }),
    );
  }

  function rollbackLegal() {
    if (!legal || !legalRollback) return;
    const reason = legalReason.trim();
    if (!reason) {
      setError("请填写法规回滚原因。");
      return;
    }
    void perform("法规发布已回滚。", () =>
      api.changeLegalPublication({
        request_id: requestId(),
        expected_sequence: legal.sequence,
        operation: "rollback",
        target_publication_id: legalRollback.publication_id,
        reason,
      }),
    );
  }

  if (identity?.role !== "admin") {
    return <Notice kind="error">当前账号无权访问配置管理。</Notice>;
  }
  if (loading) return <Loading label="正在读取法规与审查配置版本" />;

  return (
    <div className="page-wrap configuration-page">
      <PageHeading
        eyebrow="版本与审计"
        title="法规与审查配置管理"
        description="每次发布都会生成不可变版本。已启动的审查继续使用创建时冻结的配置和法规发布。"
        actions={
          <Button
            onClick={() => void perform("版本状态已刷新。", () => reload())}
            disabled={busy}
          >
            刷新状态
          </Button>
        }
      />
      {error && <Notice kind="error">{error}</Notice>}
      {message && <Notice kind="success">{message}</Notice>}

      <section className="panel" aria-labelledby="legal-management-heading">
        <div className="panel-header">
          <div>
            <p className="eyebrow">不可变法规语料</p>
            <h2 id="legal-management-heading">法规版本</h2>
          </div>
          <span className="status-badge status-ready">
            当前发布：
            {legal?.publication_id
              ? legal.publication_id.slice(0, 12)
              : "未发布"}
          </span>
        </div>
        <Notice kind="info">
          此处基于仓库已配置并校验的法规语料创建新修订，不编辑法规原文。法规发布变化后，需发布新的审查配置；执行中和已发布任务仍保留各自的历史快照。
        </Notice>
        {legal?.revisions.length ? (
          <div className="table-scroll">
            <table>
              <caption className="sr-only">法规修订历史</caption>
              <thead>
                <tr>
                  <th>草稿序号</th>
                  <th>版本内容</th>
                  <th>校验状态</th>
                  <th>操作人</th>
                  <th>说明</th>
                </tr>
              </thead>
              <tbody>
                {legal.revisions.map((revision) => (
                  <tr key={revision.revision_id}>
                    <td>
                      {revision.draft_sequence}
                      {revision.revision_id === legal.draft_revision_id
                        ? " · 当前草稿"
                        : ""}
                    </td>
                    <td>
                      {revision.versions
                        .map((version) => `${version.title} ${version.version}`)
                        .join("；")}
                    </td>
                    <td>
                      {revision.versions
                        .map((version) =>
                          version.verification === "verified"
                            ? "已核验"
                            : "待核验",
                        )
                        .join("、")}
                    </td>
                    <td>
                      <code>{revision.actor_id}</code>
                    </td>
                    <td>{revision.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="empty-state">暂无法规修订记录。</p>
        )}
        <div className="form-grid configuration-controls">
          <label className="form-field">
            <span>法规操作说明</span>
            <input
              value={legalReason}
              onChange={(event) => setLegalReason(event.target.value)}
              maxLength={1000}
            />
          </label>
          <fieldset className="configuration-actions">
            <legend className="sr-only">法规版本操作</legend>
            <Button
              onClick={createLegalDraft}
              disabled={
                busy ||
                !(
                  legal?.capabilities.includes("ingest") ||
                  legal?.capabilities.includes("verify")
                )
              }
            >
              创建法规草稿
            </Button>
            <Button
              variant="primary"
              onClick={publishLegalDraft}
              disabled={
                busy || !legalDraft || !legal?.capabilities.includes("publish")
              }
            >
              发布草稿
            </Button>
            <Button
              variant="danger"
              onClick={deactivateLegal}
              disabled={
                busy ||
                !legal?.publication_id ||
                !legal?.capabilities.includes("disable")
              }
            >
              停用当前法规
            </Button>
            <Button
              onClick={rollbackLegal}
              disabled={
                busy ||
                !legalRollback ||
                !legal?.capabilities.includes("rollback")
              }
            >
              回滚历史发布
            </Button>
          </fieldset>
        </div>
        <p className="configuration-footnote">
          可用授权：
          {legal?.capabilities.length
            ? legal.capabilities.join("、")
            : "当前账号没有法规写入授权"}
          。法规写入授权由独立服务端能力控制。
        </p>
      </section>

      <section className="panel" aria-labelledby="review-config-heading">
        <div className="panel-header">
          <div>
            <p className="eyebrow">租户审查版本</p>
            <h2 id="review-config-heading">规则、Skill 与模型策略</h2>
          </div>
          <span className="status-badge status-ready">
            当前版本：
            {activeConfig ? `v${activeConfig.revision_sequence}` : "系统默认"}
          </span>
        </div>
        <Notice kind="info">
          可选 Skill
          和规则仅来自已安装实现；模型路由和授权由服务端控制。此页面不接收、不展示
          API Key，也不会启用 DEC-002 未授权的在线模型。
        </Notice>
        {activeLegalMismatch && (
          <Notice kind="error">
            当前审查配置绑定的法规发布已不是现行发布。请创建并发布绑定当前法规版本的新配置后再创建审查任务。
          </Notice>
        )}
        {catalog && config && policy && (
          <>
            <div className="table-scroll">
              <table>
                <caption className="sr-only">
                  已安装的审查 Skill 和规则版本
                </caption>
                <thead>
                  <tr>
                    <th>启用</th>
                    <th>Skill</th>
                    <th>Skill 版本</th>
                    <th>规则版本</th>
                  </tr>
                </thead>
                <tbody>
                  {catalog.skills.map((skill) => (
                    <tr key={skill.skill_id}>
                      <td>
                        <input
                          aria-label={`启用 ${skill.skill_id}`}
                          type="checkbox"
                          checked={selectedSkills.includes(skill.skill_id)}
                          onChange={(event) =>
                            setSelectedSkills((current) =>
                              event.target.checked
                                ? [...current, skill.skill_id]
                                : current.filter(
                                    (item) => item !== skill.skill_id,
                                  ),
                            )
                          }
                        />
                      </td>
                      <td>
                        <code>{skill.skill_id}</code>
                      </td>
                      <td>{skill.skill_version}</td>
                      <td>
                        {Object.entries(skill.rule_versions)
                          .map(([id, version]) => `${id} ${version}`)
                          .join("；")}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="configuration-policy-grid">
              <label className="form-field">
                <span>模型配置档案（服务端固定）</span>
                <input value={policy.profile} readOnly />
              </label>
              <label className="form-field">
                <span>数据策略（服务端固定）</span>
                <input value={policy.data_policy} readOnly />
              </label>
              <label className="form-field">
                <span>超时上限（秒）</span>
                <input
                  type="number"
                  min="1"
                  max={catalog.model_policy.timeout_seconds}
                  value={policy.timeout_seconds}
                  onChange={(event) =>
                    setPolicy({
                      ...policy,
                      timeout_seconds: Number(event.target.value),
                    })
                  }
                />
              </label>
              <label className="form-field">
                <span>最大尝试次数</span>
                <input
                  type="number"
                  min="1"
                  max={catalog.model_policy.max_attempts}
                  value={policy.max_attempts}
                  onChange={(event) =>
                    setPolicy({
                      ...policy,
                      max_attempts: Number(event.target.value),
                    })
                  }
                />
              </label>
              <label className="form-field">
                <span>输入令牌上限</span>
                <input
                  type="number"
                  min="1"
                  max={catalog.model_policy.max_input_tokens ?? 1000000}
                  value={policy.max_input_tokens ?? ""}
                  onChange={(event) =>
                    setPolicy({
                      ...policy,
                      max_input_tokens: event.target.value
                        ? Number(event.target.value)
                        : null,
                    })
                  }
                />
              </label>
              <label className="form-field">
                <span>输出令牌上限</span>
                <input
                  type="number"
                  min="1"
                  max={catalog.model_policy.max_output_tokens ?? 1000000}
                  value={policy.max_output_tokens ?? ""}
                  onChange={(event) =>
                    setPolicy({
                      ...policy,
                      max_output_tokens: event.target.value
                        ? Number(event.target.value)
                        : null,
                    })
                  }
                />
              </label>
              <label className="form-field">
                <span>温度上限</span>
                <input
                  type="number"
                  min="0"
                  max={catalog.model_policy.temperature}
                  step="0.1"
                  value={policy.temperature}
                  onChange={(event) =>
                    setPolicy({
                      ...policy,
                      temperature: Number(event.target.value),
                    })
                  }
                />
              </label>
            </div>
            <label className="form-field configuration-reason">
              <span>配置变更说明</span>
              <input
                value={configReason}
                onChange={(event) => setConfigReason(event.target.value)}
                maxLength={1000}
              />
            </label>
            <fieldset className="configuration-actions">
              <legend className="sr-only">审查配置版本操作</legend>
              <Button
                onClick={createConfigDraft}
                disabled={
                  busy || !legal?.publication_id || selectedSkills.length === 0
                }
              >
                保存配置草稿
              </Button>
              <Button
                variant="primary"
                onClick={publishConfigDraft}
                disabled={busy || !draftConfig}
              >
                发布配置
              </Button>
              <Button
                variant="danger"
                onClick={deactivateConfig}
                disabled={busy || !activeConfig}
              >
                停用当前配置
              </Button>
              <Button
                onClick={rollbackConfigRelease}
                disabled={busy || !rollbackConfig}
              >
                回滚历史版本
              </Button>
            </fieldset>
            <p className="configuration-footnote">
              当前法规发布：{legal?.publication_id ?? "暂无"} · 配置状态序号：
              {config.sequence} · 草稿序号：{config.draft_sequence}
            </p>
            <div className="table-scroll">
              <table>
                <caption className="sr-only">审查配置发布与审计记录</caption>
                <thead>
                  <tr>
                    <th>事件序号</th>
                    <th>操作</th>
                    <th>版本号</th>
                    <th>操作人</th>
                    <th>时间</th>
                    <th>原因</th>
                  </tr>
                </thead>
                <tbody>
                  {config.events.map((event) => (
                    <tr key={event.event_id}>
                      <td>{event.sequence}</td>
                      <td>
                        {event.operation === "draft"
                          ? "创建草稿"
                          : event.operation === "publish"
                            ? "发布"
                            : event.operation === "disable"
                              ? "停用"
                              : "回滚"}
                      </td>
                      <td>
                        <code>{event.revision_id ?? "—"}</code>
                      </td>
                      <td>
                        <code>{event.actor_id}</code>
                      </td>
                      <td>
                        {new Date(event.created_at).toLocaleString("zh-CN")}
                      </td>
                      <td>{event.reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {config.items.length > 0 && (
              <details className="configuration-releases">
                <summary>查看不可变版本身份与摘要</summary>
                <ul>
                  {config.items.map((item) => (
                    <li key={item.revision_id}>
                      <strong>
                        v{item.revision_sequence} ·{" "}
                        {item.status === "active"
                          ? "生效中"
                          : item.status === "draft"
                            ? "草稿"
                            : "历史版本"}
                      </strong>
                      <code>{item.revision_id}</code>
                      <code>SHA-256 {item.snapshot_hash}</code>
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </>
        )}
      </section>
    </div>
  );
}

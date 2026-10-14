import type { FormEvent } from "react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { errorText } from "../api/client";
import {
  api,
  type Project,
  type ProjectCreate,
  type ProjectUpdate,
} from "../api/operations";
import { useAuth } from "../auth";
import {
  Button,
  Dialog,
  EmptyState,
  Loading,
  Notice,
  PageHeading,
} from "../ui";
import { clearIntentKey, formatDate, intentKey } from "../utils";

const projectTypeLabels: Record<string, string> = {
  works: "工程",
  goods: "货物",
  services: "服务",
};
const procurementLabels: Record<string, string> = {
  government: "政府采购",
  enterprise: "企业采购",
  other: "其他",
};

export function ProjectsPage() {
  const { identity } = useAuth();
  const [items, setItems] = useState<Project[]>([]);
  const [offset, setOffset] = useState(0);
  const [limit] = useState(20);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [refresh, setRefresh] = useState(0);

  // biome-ignore lint/correctness/useExhaustiveDependencies: refresh intentionally reloads the server list after a project mutation.
  useEffect(() => {
    let active = true;
    setLoading(true);
    api
      .projects(offset, limit)
      .then((data) => {
        if (!active) return;
        setItems(data.items);
        setError(null);
      })
      .catch((reason: unknown) => active && setError(errorText(reason)))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [offset, limit, refresh]);

  return (
    <section className="page-wrap">
      <PageHeading
        eyebrow="项目管理"
        title="项目工作台"
        description="查看当前账号可访问的项目、上下文版本和已持久化的审查工作。"
        actions={
          identity?.role === "reviewer" ? (
            <Button variant="primary" onClick={() => setOpen(true)}>
              ＋ 新建项目
            </Button>
          ) : undefined
        }
      />
      {error && <Notice kind="error">{error}</Notice>}
      <div className="section-heading">
        <h2>可访问项目</h2>
        <span className="muted">
          第 {Math.floor(offset / limit) + 1} 页 · 每页 {limit} 项
        </span>
      </div>
      {loading ? (
        <Loading label="正在读取项目列表" />
      ) : items.length === 0 ? (
        <EmptyState
          title="还没有可显示的项目"
          description={
            identity?.role === "reviewer"
              ? "创建项目后，可在项目页上传招标文件并查看真实处理状态。"
              : "当前账号暂时没有可访问的项目。"
          }
          action={
            identity?.role === "reviewer" ? (
              <Button variant="primary" onClick={() => setOpen(true)}>
                新建项目
              </Button>
            ) : undefined
          }
        />
      ) : (
        <div className="project-grid">
          {items.map((project) => (
            <Link
              className="project-card"
              to={`/projects/${encodeURIComponent(project.project_id)}`}
              key={project.project_id}
            >
              <div className="project-card-top">
                <span className="project-icon" aria-hidden="true">
                  项
                </span>
                <span className="version-tag">版本 {project.version}</span>
              </div>
              <h3>{project.name}</h3>
              <p className="project-region">
                {project.region} ·{" "}
                {projectTypeLabels[project.project_type] ||
                  project.project_type}
              </p>
              <div className="project-card-meta">
                <span>
                  {procurementLabels[project.procurement_type] ||
                    project.procurement_type}
                </span>
                <span>创建于 {formatDate(project.created_at)}</span>
              </div>
              <span className="project-card-link">
                打开项目 <span aria-hidden="true">→</span>
              </span>
            </Link>
          ))}
        </div>
      )}
      <div className="pagination">
        <Button
          variant="secondary"
          disabled={offset === 0 || loading}
          onClick={() => setOffset(Math.max(0, offset - limit))}
        >
          上一页
        </Button>
        <Button
          variant="secondary"
          disabled={loading || items.length < limit}
          onClick={() => setOffset(offset + limit)}
        >
          下一页
        </Button>
      </div>
      <ProjectFormDialog
        open={open}
        title="新建项目"
        onClose={() => setOpen(false)}
        onSaved={() => {
          setOpen(false);
          setOffset(0);
          setRefresh((v) => v + 1);
        }}
      />
    </section>
  );
}

export function ProjectFormDialog({
  open,
  title,
  initial,
  onClose,
  onSaved,
}: {
  open: boolean;
  title: string;
  initial?: Project;
  onClose: () => void;
  onSaved: (project: Project) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    const form = new FormData(event.currentTarget);
    const budgetText = String(form.get("budget_amount") || "").trim();
    const body: ProjectCreate = {
      name: String(form.get("name") || "").trim(),
      procurement_type: String(
        form.get("procurement_type"),
      ) as ProjectCreate["procurement_type"],
      project_type: String(
        form.get("project_type"),
      ) as ProjectCreate["project_type"],
      region: String(form.get("region") || "").trim(),
      industry: String(form.get("industry") || "").trim() || null,
      budget_amount: budgetText ? Number(budgetText) : null,
      applicable_system:
        String(form.get("applicable_system") || "").trim() || null,
      procurement_method: String(
        form.get("procurement_method"),
      ) as ProjectCreate["procurement_method"],
      buyer_type: String(form.get("buyer_type")) as ProjectCreate["buyer_type"],
      subject_type: String(
        form.get("subject_type"),
      ) as ProjectCreate["subject_type"],
      legal_frameworks: form
        .getAll("legal_frameworks")
        .map(String) as ProjectCreate["legal_frameworks"],
    };
    try {
      let saved: Project;
      if (initial) {
        const update: ProjectUpdate = {
          ...body,
          expected_version: initial.version,
        };
        saved = await api.updateProject(initial.project_id, update);
      } else {
        saved = await api.createProject(body, intentKey("create-project"));
        clearIntentKey("create-project");
      }
      onSaved(saved);
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} title={title} onClose={onClose} size="wide">
      <form className="form-grid" onSubmit={submit}>
        {error && (
          <div className="form-span">
            <Notice kind="error">{error}</Notice>
          </div>
        )}
        <div className="form-field form-span">
          <label htmlFor="project-name">
            项目名称 <span className="required-mark">*</span>
          </label>
          <input
            id="project-name"
            name="name"
            required
            maxLength={300}
            defaultValue={initial?.name || ""}
          />
        </div>
        <div className="form-field">
          <label htmlFor="procurement-type">
            采购类型 <span className="required-mark">*</span>
          </label>
          <select
            id="procurement-type"
            name="procurement_type"
            required
            defaultValue={initial?.procurement_type || "government"}
          >
            <option value="government">政府采购</option>
            <option value="enterprise">企业采购</option>
            <option value="other">其他</option>
          </select>
        </div>
        <div className="form-field">
          <label htmlFor="project-type">
            项目类型 <span className="required-mark">*</span>
          </label>
          <select
            id="project-type"
            name="project_type"
            required
            defaultValue={initial?.project_type || "works"}
          >
            <option value="works">工程</option>
            <option value="goods">货物</option>
            <option value="services">服务</option>
          </select>
        </div>
        <div className="form-field">
          <label htmlFor="region">
            地区 <span className="required-mark">*</span>
          </label>
          <input
            id="region"
            name="region"
            required
            maxLength={200}
            defaultValue={initial?.region || ""}
          />
        </div>
        <div className="form-field">
          <label htmlFor="industry">行业</label>
          <input
            id="industry"
            name="industry"
            maxLength={200}
            defaultValue={initial?.industry || ""}
          />
        </div>
        <div className="form-field">
          <label htmlFor="budget-amount">预算金额（元）</label>
          <input
            id="budget-amount"
            name="budget_amount"
            type="number"
            min="0"
            step="0.01"
            defaultValue={initial?.budget_amount ?? ""}
          />
        </div>
        <div className="form-field">
          <label htmlFor="procurement-method">采购方式</label>
          <select
            id="procurement-method"
            name="procurement_method"
            defaultValue={initial?.procurement_method || "unknown"}
          >
            <option value="unknown">未指定</option>
            <option value="tender">招标</option>
            <option value="non_tender">非招标</option>
          </select>
        </div>
        <div className="form-field">
          <label htmlFor="buyer-type">采购人类型</label>
          <select
            id="buyer-type"
            name="buyer_type"
            defaultValue={initial?.buyer_type || "unknown"}
          >
            <option value="unknown">未指定</option>
            <option value="government_entity">政府机关或事业单位</option>
            <option value="enterprise">企业</option>
            <option value="other">其他</option>
          </select>
        </div>
        <div className="form-field">
          <label htmlFor="subject-type">采购标的类型</label>
          <select
            id="subject-type"
            name="subject_type"
            defaultValue={initial?.subject_type || "unknown"}
          >
            <option value="unknown">未指定</option>
            <option value="works">工程</option>
            <option value="works_related_goods">与工程相关的货物</option>
            <option value="works_related_services">与工程相关的服务</option>
            <option value="goods">货物</option>
            <option value="services">服务</option>
          </select>
        </div>
        <fieldset className="form-field form-span">
          <legend>适用制度</legend>
          <label className="check-row">
            <input
              type="checkbox"
              name="legal_frameworks"
              value="tendering"
              defaultChecked={initial?.legal_frameworks?.includes("tendering")}
            />{" "}
            招标投标制度
          </label>
          <label className="check-row">
            <input
              type="checkbox"
              name="legal_frameworks"
              value="government_procurement"
              defaultChecked={initial?.legal_frameworks?.includes(
                "government_procurement",
              )}
            />{" "}
            政府采购制度
          </label>
        </fieldset>
        <div className="form-field form-span">
          <label htmlFor="applicable-system">其他适用制度说明</label>
          <textarea
            id="applicable-system"
            name="applicable_system"
            rows={3}
            maxLength={1000}
            defaultValue={initial?.applicable_system || ""}
          />
        </div>
        <div className="modal-actions form-span">
          <Button type="button" onClick={onClose}>
            取消
          </Button>
          <Button type="submit" variant="primary" disabled={busy}>
            {busy ? "正在保存…" : "保存项目"}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

import type { FormEvent } from "react";
import { useEffect, useState } from "react";
import { errorText } from "../api/client";
import { type AuditEvent, api } from "../api/operations";
import {
  Button,
  DataTable,
  EmptyState,
  Loading,
  Notice,
  PageHeading,
} from "../ui";
import { formatDate } from "../utils";

type AuditFilter = Parameters<typeof api.auditEvents>[0];

export function AuditPage() {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [filter, setFilter] = useState<AuditFilter>({ offset: 0, limit: 50 });
  const [draft, setDraft] = useState({
    resource_id: "",
    actor_id: "",
    action: "",
    from: "",
    to: "",
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [total, setTotal] = useState(0);

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    setLoading(true);
    api
      .auditEvents(filter, { signal: controller.signal })
      .then((response) => {
        if (!active) return;
        setEvents(response.items);
        setTotal(response.total);
        setError(null);
      })
      .catch((reason: unknown) => active && setError(errorText(reason)))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
      controller.abort();
    };
  }, [filter]);

  function apply(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFilter({
      resource_id: draft.resource_id.trim() || undefined,
      actor_id: draft.actor_id.trim() || undefined,
      action: draft.action.trim() || undefined,
      from: draft.from ? new Date(draft.from).toISOString() : undefined,
      to: draft.to ? new Date(draft.to).toISOString() : undefined,
      offset: 0,
      limit: 50,
    });
  }

  return (
    <section className="page-wrap">
      <PageHeading
        eyebrow="只读查询"
        title="审计记录"
        description="服务端按当前租户范围过滤。查询操作本身也会进入审计。"
      />
      {error && <Notice kind="error">{error}</Notice>}
      <form className="filter-panel" onSubmit={apply}>
        <label className="form-field">
          资源编号
          <input
            value={draft.resource_id}
            onChange={(event) =>
              setDraft({ ...draft, resource_id: event.target.value })
            }
            maxLength={64}
          />
        </label>
        <label className="form-field">
          操作人编号
          <input
            value={draft.actor_id}
            onChange={(event) =>
              setDraft({ ...draft, actor_id: event.target.value })
            }
            maxLength={64}
          />
        </label>
        <label className="form-field">
          操作类型
          <input
            value={draft.action}
            onChange={(event) =>
              setDraft({ ...draft, action: event.target.value })
            }
            maxLength={100}
          />
        </label>
        <label className="form-field">
          开始时间
          <input
            type="datetime-local"
            value={draft.from}
            onChange={(event) =>
              setDraft({ ...draft, from: event.target.value })
            }
          />
        </label>
        <label className="form-field">
          结束时间
          <input
            type="datetime-local"
            value={draft.to}
            onChange={(event) => setDraft({ ...draft, to: event.target.value })}
          />
        </label>
        <div className="filter-actions">
          <Button type="submit" variant="primary">
            查询记录
          </Button>
          <Button
            type="button"
            onClick={() => {
              setDraft({
                resource_id: "",
                actor_id: "",
                action: "",
                from: "",
                to: "",
              });
              setFilter({ offset: 0, limit: 50 });
            }}
          >
            清除筛选
          </Button>
        </div>
      </form>
      <div className="section-heading">
        <h2>查询结果</h2>
        <span className="muted">
          共 {total} 条 · 当前显示 {events.length} 条
        </span>
      </div>
      {loading ? (
        <Loading label="正在查询审计记录" />
      ) : events.length === 0 ? (
        <EmptyState
          title="没有匹配的审计记录"
          description="调整筛选条件后重新查询。"
        />
      ) : (
        <DataTable label="审计记录查询结果">
          <thead>
            <tr>
              <th scope="col">时间</th>
              <th scope="col">操作人</th>
              <th scope="col">操作类型</th>
              <th scope="col">资源</th>
              <th scope="col">请求编号</th>
            </tr>
          </thead>
          <tbody>
            {events.map((item) => (
              <tr key={item.event_id}>
                <td>{formatDate(item.occurred_at)}</td>
                <td>{item.actor_id || "系统"}</td>
                <td>
                  <code>{item.action}</code>
                </td>
                <td>
                  {item.resource_id ? <code>{item.resource_id}</code> : "—"}
                </td>
                <td>
                  <code>{item.request_id}</code>
                </td>
              </tr>
            ))}
          </tbody>
        </DataTable>
      )}
      <div className="pagination">
        <Button
          disabled={(filter.offset ?? 0) === 0 || loading}
          onClick={() =>
            setFilter((current) => ({
              ...current,
              offset: Math.max(0, (current.offset ?? 0) - 50),
            }))
          }
        >
          上一页
        </Button>
        <Button
          disabled={loading || (filter.offset ?? 0) + events.length >= total}
          onClick={() =>
            setFilter((current) => ({
              ...current,
              offset: (current.offset ?? 0) + 50,
            }))
          }
        >
          下一页
        </Button>
      </div>
    </section>
  );
}

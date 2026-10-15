import { useState } from "react";
import {
  Navigate,
  NavLink,
  Outlet,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";
import { useAuth } from "./auth";
import { AuditPage } from "./pages/audit";
import { ConfigurationPage } from "./pages/configuration";
import { LoginPage } from "./pages/login";
import { ProjectPage } from "./pages/project";
import { ProjectsPage } from "./pages/projects";
import { PendingReviewsPage, ReviewPage } from "./pages/reviews";
import { Button, Loading } from "./ui";

const roleNames: Record<string, string> = {
  reviewer: "审核员",
  auditor: "审计员",
  admin: "管理员",
  operator: "运维人员",
};

function OfflineDemoNotice() {
  if (import.meta.env.VITE_REVIEW_MODE !== "offline-deterministic") return null;
  return (
    <aside
      className="offline-demo-notice"
      data-testid="offline-demo-notice"
      aria-label="执行模式说明"
      role="note"
    >
      <strong>离线确定性演示</strong>
      <span>
        本次模型分析由固定测试网关生成，用于验证工作流和证据链；不代表
        Qwen、DeepSeek 或其他在线大模型的语义审查能力。
      </span>
    </aside>
  );
}

function OnlineQwenDemoNotice() {
  const realTender = import.meta.env.VITE_REVIEW_MODE === "dec005-real-qwen";
  if (import.meta.env.VITE_REVIEW_MODE !== "online-qwen" && !realTender)
    return null;
  return (
    <aside
      className="online-qwen-demo-notice"
      data-testid="online-qwen-demo-notice"
      aria-label="在线执行模式说明"
      role="note"
    >
      <strong>
        {realTender
          ? "已配置真实模型路由：阿里云百炼 qwen3.8-flash"
          : "真实在线模型：阿里云百炼 qwen3.8-flash"}
      </strong>
      <span>
        {realTender
          ? "DEC-005 仅授权指定文件的脱敏分段；AI 独立发现疑点后进入法规检索与人工复核。实际供应商响应及用量见任务详情。缺少有效法规的疑点保持待核验。"
          : "仅允许 TASK-0021 合成文件进入 semantic_analysis。法规正文留在本地核验。"}
        请求失败会停止审查。
      </span>
    </aside>
  );
}

function AuthRequired() {
  const auth = useAuth();
  const location = useLocation();
  if (auth.loading) return <Loading label="正在验证登录状态" />;
  if (!auth.identity)
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return <Outlet />;
}

function AppShell() {
  const { identity, signOut } = useAuth();
  const navigate = useNavigate();
  const [signingOut, setSigningOut] = useState(false);

  async function exit() {
    setSigningOut(true);
    await signOut();
    setSigningOut(false);
    navigate("/login", { replace: true });
  }

  return (
    <div className="app-shell">
      <aside className="sidebar" aria-label="主导航">
        <div className="brand-lockup">
          <span className="brand-mark" aria-hidden="true">
            招
          </span>
          <span>
            <strong>合规审查</strong>
            <small>业务工作台</small>
          </span>
        </div>
        <nav className="nav-list">
          <NavLink
            to="/projects"
            className={({ isActive }) =>
              isActive ? "nav-link active" : "nav-link"
            }
          >
            <span aria-hidden="true">▦</span> 项目工作台
          </NavLink>
          {identity?.role === "reviewer" && (
            <NavLink
              to="/reviews"
              className={({ isActive }) =>
                isActive ? "nav-link active" : "nav-link"
              }
            >
              <span aria-hidden="true">✓</span> 待复核任务
            </NavLink>
          )}
          {identity?.role === "auditor" && (
            <NavLink
              to="/audit"
              className={({ isActive }) =>
                isActive ? "nav-link active" : "nav-link"
              }
            >
              <span aria-hidden="true">≡</span> 审计记录
            </NavLink>
          )}
          {identity?.role === "admin" && (
            <NavLink
              to="/configurations"
              className={({ isActive }) =>
                isActive ? "nav-link active" : "nav-link"
              }
            >
              <span aria-hidden="true">⚙</span> 配置版本
            </NavLink>
          )}
        </nav>
        <div className="sidebar-footnote">
          <span className="status-dot" aria-hidden="true" />
          状态与结论来自服务端
        </div>
      </aside>
      <div className="main-column">
        <header className="topbar">
          <div className="breadcrumb">
            招标合规审查 <span aria-hidden="true">/</span> 工作台
          </div>
          <div className="user-menu">
            <span className="user-avatar" aria-hidden="true">
              {identity?.username.slice(0, 1) || "用"}
            </span>
            <span className="user-label">
              <strong>{identity?.username}</strong>
              <small>{identity && roleNames[identity.role]} · 当前租户</small>
            </span>
            <Button
              variant="quiet"
              onClick={() => void exit()}
              disabled={signingOut}
            >
              {signingOut ? "正在退出" : "退出登录"}
            </Button>
          </div>
        </header>
        <main id="main-content" className="main-content" tabIndex={-1}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}

function NotFound() {
  return (
    <section className="page-wrap">
      <h1>页面不存在</h1>
      <p>此地址没有对应的业务页面，或当前账号无权访问。</p>
      <NavLink className="button button-primary" to="/projects">
        返回项目工作台
      </NavLink>
    </section>
  );
}

export function App() {
  return (
    <>
      <OfflineDemoNotice />
      <OnlineQwenDemoNotice />
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<AuthRequired />}>
          <Route element={<AppShell />}>
            <Route index element={<Navigate to="/projects" replace />} />
            <Route path="projects" element={<ProjectsPage />} />
            <Route path="projects/:projectId" element={<ProjectPage />} />
            <Route path="reviews" element={<PendingReviewsPage />} />
            <Route
              path="reviews/:reviewTaskId/:runId"
              element={<ReviewPage />}
            />
            <Route path="audit" element={<AuditPage />} />
            <Route path="configurations" element={<ConfigurationPage />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/projects" replace />} />
      </Routes>
    </>
  );
}

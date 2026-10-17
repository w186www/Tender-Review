import type { FormEvent } from "react";
import { useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth";

type LoginLocation = { from?: string };

export function LoginPage() {
  const { identity, loading, signIn, error } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const state = location.state as LoginLocation | null;
  const [tenant, setTenant] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  if (identity) return <Navigate to={state?.from || "/projects"} replace />;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const ok = await signIn(tenant.trim(), username.trim(), password);
    if (ok) navigate(state?.from || "/projects", { replace: true });
    setPassword("");
  }

  return (
    <main className="login-page">
      <section className="login-card" aria-labelledby="login-title">
        <div className="brand-mark brand-mark-large" aria-hidden="true">
          招
        </div>
        <p className="eyebrow">BIDDING COMPLIANCE WORKSPACE</p>
        <h1 id="login-title">登录审查工作台</h1>
        <p className="muted">
          使用已开通的租户账号。系统不会在网页中开放账号注册或角色变更。
        </p>
        <form onSubmit={submit} className="form-stack">
          <label htmlFor="tenant">租户编号</label>
          <input
            id="tenant"
            name="tenant"
            autoComplete="organization"
            required
            maxLength={64}
            value={tenant}
            onChange={(event) => setTenant(event.target.value)}
          />
          <label htmlFor="username">用户名</label>
          <input
            id="username"
            name="username"
            autoComplete="username"
            required
            maxLength={100}
            value={username}
            onChange={(event) => setUsername(event.target.value)}
          />
          <label htmlFor="password">密码</label>
          <input
            id="password"
            name="password"
            type="password"
            autoComplete="current-password"
            required
            maxLength={1024}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
          {error && (
            <p className="error-message" role="alert">
              {error}
            </p>
          )}
          <button
            className="button button-primary button-wide"
            type="submit"
            disabled={loading}
          >
            {loading ? "正在验证身份…" : "登录"}
          </button>
        </form>
        <p className="login-foot">
          访问权限由服务端逐次验证。登录令牌仅保存在当前浏览器标签页。
        </p>
      </section>
    </main>
  );
}

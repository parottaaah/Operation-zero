import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { describeError } from "../lib/api";
import { Field, Notice, Spinner } from "../components/ui";

export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
      const target = (location.state as { from?: string } | null)?.from ?? "/";
      navigate(target, { replace: true });
    } catch (cause) {
      setError(describeError(cause));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="brand">
          <span className="brand-mark">
            <span className="brand-dot" aria-hidden="true" />
            OPERATION ZERO
          </span>
          <span className="brand-sub">engineering operations &amp; incident intelligence</span>
        </div>
        <h1>Sign in</h1>
        <p className="auth-sub">
          Monitoring, structured logs, alerts, incidents and evidence-grounded investigation in
          one workspace.
        </p>
        <form onSubmit={submit} className="stack" aria-describedby={error ? "login-error" : undefined}>
          {error && (
            <div id="login-error">
              <Notice tone="error">{error}</Notice>
            </div>
          )}
          <Field label="Email">
            <input
              className="input"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </Field>
          <Field label="Password">
            <input
              className="input"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </Field>
          <button className="btn primary" type="submit" disabled={busy}>
            {busy ? <Spinner /> : null}
            Sign in
          </button>
        </form>
        <div className="auth-footer">
          New here? <Link to="/register">Create a workspace</Link>
        </div>
      </div>
    </div>
  );
}

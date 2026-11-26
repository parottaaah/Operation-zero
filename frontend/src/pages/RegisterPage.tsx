import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { describeError } from "../lib/api";
import { Field, Notice, Spinner } from "../components/ui";

export default function RegisterPage() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [workspaceName, setWorkspaceName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await register(email, fullName, password, workspaceName);
      navigate("/", { replace: true });
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
        <h1>Create your workspace</h1>
        <p className="auth-sub">
          You become the workspace owner. Add teammates later with explicit roles.
        </p>
        <form onSubmit={submit} className="stack">
          {error && <Notice tone="error">{error}</Notice>}
          <Field label="Full name">
            <input
              className="input"
              autoComplete="name"
              value={fullName}
              onChange={(event) => setFullName(event.target.value)}
            />
          </Field>
          <Field label="Work email">
            <input
              className="input"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </Field>
          <Field label="Password" hint="At least 12 characters, with letters and numbers.">
            <input
              className="input"
              type="password"
              autoComplete="new-password"
              required
              minLength={12}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </Field>
          <Field label="Workspace name">
            <input
              className="input"
              required
              minLength={2}
              placeholder="Acme Platform"
              value={workspaceName}
              onChange={(event) => setWorkspaceName(event.target.value)}
            />
          </Field>
          <button className="btn primary" type="submit" disabled={busy}>
            {busy ? <Spinner /> : null}
            Create workspace
          </button>
        </form>
        <div className="auth-footer">
          Already have an account? <Link to="/login">Sign in</Link>
        </div>
      </div>
    </div>
  );
}

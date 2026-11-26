import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { api } from "../lib/api";
import type { Overview } from "../lib/types";
import { useAsync } from "../hooks/useAsync";
import { Badge } from "./ui";

interface NavItem {
  to: string;
  label: string;
  glyph: string;
  end?: boolean;
}

const NAV: Array<{ group: string; items: NavItem[] }> = [
  {
    group: "Operate",
    items: [
      { to: "/", label: "Overview", glyph: "◎", end: true },
      { to: "/services", label: "Services", glyph: "⬡" },
      { to: "/logs", label: "Logs", glyph: "≣" },
      { to: "/alerts", label: "Alerts", glyph: "▲" },
      { to: "/incidents", label: "Incidents", glyph: "◉" },
    ],
  },
  {
    group: "Context",
    items: [
      { to: "/deployments", label: "Deployments", glyph: "⑂" },
      { to: "/security", label: "Security", glyph: "⛨" },
      { to: "/integrations", label: "Integrations", glyph: "⇄" },
    ],
  },
  {
    group: "Govern",
    items: [
      { to: "/reports", label: "Reports", glyph: "▤" },
      { to: "/settings", label: "Settings", glyph: "⚙" },
    ],
  },
];

export default function Layout() {
  const { me, workspace, role, logout, selectWorkspace } = useAuth();
  const navigate = useNavigate();

  const overview = useAsync<Overview>(
    (signal) =>
      workspace
        ? api<Overview>(`/workspaces/${workspace.id}/overview`, { signal })
        : Promise.resolve(null as unknown as Overview),
    [workspace?.id],
  );

  const activeIncidents = overview.data?.active_incidents.length ?? 0;

  return (
    <div className="app-shell">
      <aside className="sidebar" aria-label="Main navigation">
        <NavLink to="/" className="brand">
          <span className="brand-mark">
            <span className="brand-dot" aria-hidden="true" />
            OPERATION ZERO
          </span>
          <span className="brand-sub">engineering operations</span>
        </NavLink>

        {NAV.map((group) => (
          <div key={group.group}>
            <div className="nav-group-label">{group.group}</div>
            {group.items.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}
              >
                <span className="nav-glyph" aria-hidden="true">
                  {item.glyph}
                </span>
                {item.label}
                {item.to === "/incidents" && activeIncidents > 0 && (
                  <span className="nav-badge" aria-label={`${activeIncidents} active incidents`}>
                    {activeIncidents}
                  </span>
                )}
              </NavLink>
            ))}
          </div>
        ))}

        <div className="sidebar-footer">
          <div>MVP · evidence before explanation</div>
          <div style={{ marginTop: 4 }}>AI is read-only and human-reviewed</div>
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          {me && me.memberships.length > 1 ? (
            <label className="row" style={{ gap: 6 }}>
              <span className="stat-label">Workspace</span>
              <select
                className="workspace-select"
                value={workspace?.id ?? ""}
                onChange={(event) => void selectWorkspace(event.target.value)}
                aria-label="Select workspace"
              >
                {me.memberships.map((membership) => (
                  <option key={membership.workspace_id} value={membership.workspace_id}>
                    {membership.workspace_name}
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <div className="row" style={{ gap: 8 }}>
              <span className="stat-label">Workspace</span>
              <strong>{workspace?.name ?? "—"}</strong>
            </div>
          )}

          <div className="spacer" />

          {role && <Badge value={role.replace("_", " ")} className="plain" />}
          {workspace?.timezone && <span className="stat-label">{workspace.timezone}</span>}
          <div className="user-chip">
            <span>{me?.user.email}</span>
            <button
              type="button"
              className="btn ghost small"
              onClick={() => {
                logout();
                navigate("/login");
              }}
            >
              Sign out
            </button>
          </div>
        </header>

        <main>
          <Outlet />
        </main>
      </div>
    </div>
  );
}

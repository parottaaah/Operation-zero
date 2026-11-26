import type { ReactNode } from "react";
import { Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import Layout from "./components/Layout";
import { EmptyState, LoadingBlock } from "./components/ui";
import LoginPage from "./pages/LoginPage";
import OverviewPage from "./pages/OverviewPage";
import PlannedPage from "./pages/PlannedPage";
import RegisterPage from "./pages/RegisterPage";
import ServicesPage from "./pages/ServicesPage";

function BootScreen() {
  return (
    <div className="page" aria-busy="true">
      <LoadingBlock lines={6} />
    </div>
  );
}

/** Sends unauthenticated visitors to the sign-in screen and remembers where they were. */
function RequireAuth({ children }: { children: ReactNode }) {
  const { me, loading } = useAuth();
  const location = useLocation();

  if (loading) return <BootScreen />;
  if (!me) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return <>{children}</>;
}

/** A signed-in user with no workspace has nothing tenant-scoped to show. */
function RequireWorkspace() {
  const { workspace, me, loading } = useAuth();

  if (loading) return <BootScreen />;
  if (!workspace) {
    return (
      <div className="page">
        <EmptyState
          title="No workspace yet"
          action={
            <a className="btn primary" href="/register">
              Create a workspace
            </a>
          }
        >
          {me?.user.email} is not a member of any workspace. Ask an owner for an invitation, or
          create your own workspace to start monitoring a service.
        </EmptyState>
      </div>
    );
  }
  return <Outlet />;
}

export default function App() {
  const { me, loading } = useAuth();

  if (loading) return <BootScreen />;

  return (
    <Routes>
      <Route path="/login" element={me ? <Navigate to="/" replace /> : <LoginPage />} />
      <Route path="/register" element={me ? <Navigate to="/" replace /> : <RegisterPage />} />

      <Route
        path="/"
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route element={<RequireWorkspace />}>
          <Route index element={<OverviewPage />} />
          <Route path="services" element={<ServicesPage />} />
          <Route path="logs" element={<PlannedPage screen="logs" />} />
          <Route path="alerts" element={<PlannedPage screen="alerts" />} />
          <Route path="incidents" element={<PlannedPage screen="incidents" />} />
          <Route path="incidents/:incidentId" element={<PlannedPage screen="incident" />} />
          <Route path="deployments" element={<PlannedPage screen="deployments" />} />
          <Route path="security" element={<PlannedPage screen="security" />} />
          <Route path="integrations" element={<PlannedPage screen="integrations" />} />
          <Route path="reports" element={<PlannedPage screen="reports" />} />
          <Route path="settings" element={<PlannedPage screen="settings" />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api, tokens, workspaceStore } from "../lib/api";
import type { Me, Role, Workspace } from "../lib/types";

interface AuthContextValue {
  me: Me | null;
  workspace: Workspace | null;
  role: Role | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, fullName: string, password: string, workspaceName: string) => Promise<void>;
  logout: () => void;
  selectWorkspace: (workspaceId: string) => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [loading, setLoading] = useState(true);

  const loadWorkspace = useCallback(async (workspaceId: string) => {
    workspaceStore.set(workspaceId);
    const detail = await api<Workspace>(`/workspaces/${workspaceId}`);
    setWorkspace(detail);
  }, []);

  const loadSession = useCallback(async () => {
    if (!tokens.access()) {
      setMe(null);
      setWorkspace(null);
      setLoading(false);
      return;
    }
    try {
      const profile = await api<Me>("/auth/me");
      setMe(profile);
      if (profile.memberships.length === 0) {
        setWorkspace(null);
        return;
      }
      const stored = workspaceStore.get();
      const chosen =
        profile.memberships.find((membership) => membership.workspace_id === stored) ??
        profile.memberships[0];
      await loadWorkspace(chosen.workspace_id);
    } catch {
      tokens.clear();
      setMe(null);
      setWorkspace(null);
    } finally {
      setLoading(false);
    }
  }, [loadWorkspace]);

  useEffect(() => {
    void loadSession();
  }, [loadSession]);

  useEffect(() => {
    const handler = () => {
      setMe(null);
      setWorkspace(null);
    };
    window.addEventListener("oz:unauthorized", handler);
    return () => window.removeEventListener("oz:unauthorized", handler);
  }, []);

  const login = useCallback(
    async (email: string, password: string) => {
      const pair = await api<{ access_token: string; refresh_token: string }>("/auth/login", {
        method: "POST",
        body: { email, password },
      });
      tokens.set(pair.access_token, pair.refresh_token);
      setLoading(true);
      await loadSession();
    },
    [loadSession],
  );

  const register = useCallback(
    async (email: string, fullName: string, password: string, workspaceName: string) => {
      const pair = await api<{ access_token: string; refresh_token: string }>("/auth/register", {
        method: "POST",
        body: { email, full_name: fullName, password, workspace_name: workspaceName },
      });
      tokens.set(pair.access_token, pair.refresh_token);
      setLoading(true);
      await loadSession();
    },
    [loadSession],
  );

  const logout = useCallback(() => {
    tokens.clear();
    workspaceStore.clear();
    setMe(null);
    setWorkspace(null);
  }, []);

  const selectWorkspace = useCallback(
    async (workspaceId: string) => {
      setLoading(true);
      try {
        await loadWorkspace(workspaceId);
      } finally {
        setLoading(false);
      }
    },
    [loadWorkspace],
  );

  const refresh = useCallback(async () => {
    await loadSession();
  }, [loadSession]);

  const role = workspace?.role ?? null;
  const value = useMemo(
    () => ({ me, workspace, role, loading, login, register, logout, selectWorkspace, refresh }),
    [me, workspace, role, loading, login, register, logout, selectWorkspace, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}

export function canWrite(role: Role | null, area: "services" | "alerts" | "incidents" | "integrations" | "ai"): boolean {
  if (!role) return false;
  const rights: Record<Role, string[]> = {
    owner: ["services", "alerts", "incidents", "integrations", "ai", "members", "audit"],
    admin: ["services", "alerts", "incidents", "integrations", "ai", "members", "audit"],
    engineer: ["services", "alerts", "incidents", "ai"],
    security_analyst: ["alerts", "incidents", "audit"],
    viewer: [],
  };
  return rights[role].includes(area);
}

export function canReadRawTelemetry(role: Role | null): boolean {
  return role !== null && role !== "viewer";
}

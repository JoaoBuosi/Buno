import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import * as api from "../lib/api";

interface AuthContextValue {
  isAuthenticated: boolean;
  loading: boolean;
  user: api.User | null;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, name: string) => Promise<void>;
  logout: () => void;
  setMemoryEnabled: (enabled: boolean) => Promise<void>;
}
const AuthContext = createContext<AuthContextValue | null>(null);
export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setCurrentToken] = useState(api.getToken);
  const [user, setUser] = useState<api.User | null>(null);
  const [loading, setLoading] = useState(!!token);
  useEffect(() => {
    const sync = () => { const next = api.getToken(); setCurrentToken(next); setLoading(!!next); setUser(null); };
    const storage = (event: StorageEvent) => { if (event.key === "buno_token") sync(); };
    window.addEventListener("buno-session", sync);
    window.addEventListener("storage", storage);
    return () => { window.removeEventListener("buno-session", sync); window.removeEventListener("storage", storage); };
  }, []);
  useEffect(() => {
    if (!token) return;
    const controller = new AbortController();
    api.getProfile(controller.signal).then(profile => { if (!controller.signal.aborted) setUser(profile); }).catch(() => {}).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [token]);
  async function accept(result: { access_token: string }) {
    api.setToken(result.access_token); setLoading(true); setUser(null); setCurrentToken(result.access_token);
  }
  async function login(email: string, password: string) { await accept(await api.login(email, password)); }
  async function register(email: string, password: string, name: string) { await accept(await api.register(email, password, name)); }
  function logout() { api.clearToken(); setUser(null); setCurrentToken(null); }
  async function setMemoryEnabled(enabled: boolean) { setUser(await api.updatePreferences(enabled)); }
  return <AuthContext.Provider value={{ isAuthenticated: !!token, loading, user, login, register, logout, setMemoryEnabled }}>{children}</AuthContext.Provider>;
}
// Kept together so consumers use the same provider instance.
// oxlint-disable-next-line react/only-export-components
export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth precisa estar dentro de AuthProvider");
  return context;
}

import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
export default function ProtectedRoute({ children }: { children: ReactNode }) {
  const { isAuthenticated, loading } = useAuth();
  if (loading) return <div role="status" className="grid h-full place-items-center text-text-muted">Abrindo a Buno…</div>;
  if (!isAuthenticated) return <Navigate to="/login" replace />;
  return children;
}

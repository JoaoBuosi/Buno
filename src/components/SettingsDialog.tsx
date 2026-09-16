import { useEffect, useRef, useState } from "react";
import { Trash2, X } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import * as api from "../lib/api";
export default function SettingsDialog({ onClose }: { onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const { user, setMemoryEnabled } = useAuth();
  const [memories, setMemories] = useState<api.Memory[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    dialog.current?.showModal(); let active = true;
    api.listMemories().then(items => { if (active) setMemories(items); }).catch(e => { if (active) setError(e.message); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);
  async function toggle(enabled: boolean) {
    setBusy(true); setError("");
    try { await setMemoryEnabled(enabled); } catch (e) { setError(e instanceof Error ? e.message : "Não foi possível salvar."); }
    finally { setBusy(false); }
  }
  async function remove(id: string) {
    setBusy(true); setError("");
    try { await api.deleteMemory(id); setMemories(items => items.filter(m => m.id !== id)); }
    catch (e) { setError(e instanceof Error ? e.message : "Não foi possível excluir."); }
    finally { setBusy(false); }
  }
  return <dialog ref={dialog} onCancel={onClose} aria-labelledby="settings-title" className="m-auto max-h-[85dvh] w-[min(92vw,520px)] overflow-y-auto rounded-2xl border border-border bg-surface p-6 text-text shadow-2xl backdrop:bg-black/70">
    <div className="mb-5 flex items-center justify-between"><h2 id="settings-title" className="text-lg font-semibold">Sua Buno</h2><button onClick={onClose} aria-label="Fechar configurações" className="rounded-lg p-2 hover:bg-surface-hover"><X size={18} /></button></div>
    <p className="mb-5 break-all text-sm text-text-muted">{user?.name}<br />{user?.email}</p>
    <label className="flex cursor-pointer items-center justify-between gap-4 text-sm font-medium">Lembrar entre conversas<input type="checkbox" className="h-5 w-5 accent-accent" checked={user?.memory_enabled ?? false} disabled={busy || !user} onChange={e => toggle(e.target.checked)} /></label>
    <p className="mt-2 text-sm leading-6 text-text-muted">Quando ativado, a Buno pode guardar preferências para usar em outros chats. Desativar impede novas memórias e o uso das existentes. Você pode apagá-las abaixo.</p>
    {error && <p role="alert" className="mt-4 text-sm text-red-300">{error}</p>}
    <h3 className="mb-3 mt-6 text-sm font-medium">Memórias salvas</h3>
    {loading ? <p role="status" className="text-sm text-text-muted">Carregando…</p> : memories.length === 0 ? <p className="text-sm text-text-muted">Nenhuma memória salva.</p> : <ul className="space-y-2">{memories.map(m => <li key={m.id} className="flex items-start gap-3 rounded-lg border border-border p-3 text-sm"><span className="min-w-0 flex-1 break-words">{m.content}</span><button disabled={busy} onClick={() => remove(m.id)} aria-label={`Apagar memória: ${m.content}`} className="p-1 text-text-muted hover:text-red-300"><Trash2 size={16} /></button></li>)}</ul>}
  </dialog>;
}

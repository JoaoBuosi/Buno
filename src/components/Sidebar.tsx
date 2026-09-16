import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Bot, FolderClosed, LogOut, PanelLeftClose, PanelLeftOpen, SquarePen, Trash2, Pencil, Settings, Search } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import * as api from "../lib/api";
import SettingsDialog from "./SettingsDialog";
import bunoLogo from "../assets/buno-logo.png";
interface Props {
  conversations: api.Conversation[]; activeConversationId: string | null;
  onNewChat: () => void; onSelectConversation: (id: string) => void;
  onDeleteConversation: (id: string) => void | Promise<void>;
  onRenameConversation?: (conversation: api.Conversation) => void;
}
export default function Sidebar({ conversations, activeConversationId, onNewChat, onSelectConversation, onDeleteConversation, onRenameConversation }: Props) {
  const { logout, user } = useAuth();
  const [collapsed, setCollapsed] = useState(() => window.innerWidth < 768);
  const [settings, setSettings] = useState(false);
  const [search, setSearch] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [titles, setTitles] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const isProjects = location.pathname.startsWith("/projects");
  const isAgents = location.pathname.startsWith("/agents");
  const name = user?.name || user?.email.split("@")[0] || "Minha conta";
  const iconClass = "grid h-9 w-9 shrink-0 place-items-center rounded-lg text-text-muted hover:bg-surface-hover hover:text-text";
  function select(action: () => void) { action(); if (window.innerWidth < 768) setCollapsed(true); }
  async function rename(id: string) {
    if (!title.trim() || busy) return; setBusy(true); setError("");
    try { const updated = await api.renameConversation(id, title.trim()); setTitles(old => ({ ...old, [id]: updated.title })); onRenameConversation?.(updated); setEditing(null); }
    catch (e) { setError(e instanceof Error ? e.message : "Não foi possível renomear."); } finally { setBusy(false); }
  }
  async function remove(id: string) {
    if (!window.confirm("Excluir esta conversa? As mensagens serão apagadas.")) return;
    setBusy(true); setError("");
    try { await onDeleteConversation(id); } catch (e) { setError(e instanceof Error ? e.message : "Não foi possível excluir."); } finally { setBusy(false); }
  }
  return <>
    {!collapsed && <button aria-label="Fechar menu" className="fixed inset-0 z-30 bg-black/60 md:hidden" onClick={() => setCollapsed(true)} />}
    <aside aria-label="Navegação principal" className={`flex h-full shrink-0 flex-col border-r border-border bg-bg ${collapsed ? "w-14 items-center gap-2 py-3" : "fixed inset-y-0 left-0 z-40 w-64 p-3 md:static md:z-auto"}`}>
      <div className={`mb-3 flex items-center ${collapsed ? "flex-col gap-3" : "justify-between px-1"}`}>
        <button onClick={() => select(onNewChat)} aria-label="Buno, início" className="flex items-center gap-2"><img src={bunoLogo} alt="" className="h-8 w-8 rounded-lg object-cover" />{!collapsed && <span className="font-semibold tracking-tight">Buno</span>}</button>
        <button onClick={() => setCollapsed(!collapsed)} aria-label={collapsed ? "Abrir menu" : "Recolher menu"} className={iconClass}>{collapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}</button>
      </div>
      <button onClick={() => select(onNewChat)} title="Nova conversa" className={collapsed ? iconClass : "mb-1 flex items-center gap-2 rounded-lg px-3 py-2.5 text-sm hover:bg-surface-hover"}><SquarePen size={17} />{!collapsed && "Nova conversa"}</button>
      <button onClick={() => select(() => navigate("/projects"))} title="Projetos" className={collapsed ? iconClass : `mb-4 flex items-center gap-2 rounded-lg px-3 py-2.5 text-sm ${isProjects ? "bg-surface-hover text-text" : "text-text-muted hover:bg-surface-hover"}`}><FolderClosed size={17} />{!collapsed && "Projetos"}</button>
      <button onClick={() => select(() => navigate("/agents"))} title="Agents" className={collapsed ? iconClass : `mb-4 flex items-center gap-2 rounded-lg px-3 py-2.5 text-sm ${isAgents ? "bg-surface-hover text-text" : "text-text-muted hover:bg-surface-hover"}`}><Bot size={17} />{!collapsed && "Agents"}</button>
      {!collapsed && <>
        <label className="mb-5 flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-text-muted"><Search size={14} /><input aria-label="Buscar conversas" placeholder="Buscar conversas" value={search} onChange={e => setSearch(e.target.value)} className="min-w-0 bg-transparent text-xs outline-none" /></label>
        <p className="mb-2 px-3 text-[10px] font-medium tracking-[.12em] text-text-muted">SUAS CONVERSAS</p>
        <div className="min-h-0 flex-1 space-y-1 overflow-y-auto">
          {!conversations.length && <p className="px-3 py-2 text-xs text-text-muted">Sua próxima ideia começa aqui.</p>}
          {conversations.filter(c => (titles[c.id] || c.title).toLocaleLowerCase().includes(search.toLocaleLowerCase())).map(c => <div key={c.id} className={`group rounded-lg ${c.id === activeConversationId ? "bg-surface-hover" : "hover:bg-surface"}`}>
            {editing === c.id ? <form onSubmit={e => { e.preventDefault(); void rename(c.id); }} className="p-2"><input autoFocus aria-label="Título da conversa" value={title} maxLength={255} onChange={e => setTitle(e.target.value)} onKeyDown={e => { if (e.key === "Escape") setEditing(null); }} className="w-full rounded border border-accent bg-bg p-1 text-xs outline-none" /><div className="mt-2 flex gap-3 text-xs"><button disabled={busy || !title.trim()} className="text-accent">Salvar</button><button type="button" onClick={() => setEditing(null)}>Cancelar</button></div></form> : <div className="flex items-center pl-3 pr-1">
              <button onClick={() => select(() => onSelectConversation(c.id))} title={titles[c.id] || c.title} aria-current={c.id === activeConversationId ? "page" : undefined} className="min-w-0 flex-1 truncate py-2.5 text-left text-xs text-text-muted hover:text-text">{titles[c.id] || c.title}</button>
              <div className="flex opacity-100 md:opacity-0 md:group-hover:opacity-100 md:group-focus-within:opacity-100"><button disabled={busy} aria-label={`Renomear ${titles[c.id] || c.title}`} onClick={() => { setEditing(c.id); setTitle(titles[c.id] || c.title); }} className="p-1.5 text-text-muted hover:text-text"><Pencil size={12} /></button><button disabled={busy} aria-label={`Excluir ${titles[c.id] || c.title}`} onClick={() => remove(c.id)} className="p-1.5 text-text-muted hover:text-red-300"><Trash2 size={12} /></button></div>
            </div>}
          </div>)}
        </div>
        {error && <p role="alert" className="px-2 py-2 text-xs text-red-300">{error}</p>}
      </>}
      {collapsed && <div className="flex-1" />}
      <div className={collapsed ? "flex flex-col gap-2" : "mt-3 flex items-center gap-1 border-t border-border pt-3"}>
        <button onClick={() => setSettings(true)} aria-label="Configurações e memórias" title="Configurações e memórias" className={collapsed ? iconClass : "flex min-w-0 flex-1 items-center gap-2 rounded-lg p-1.5 text-sm hover:bg-surface-hover"}>{collapsed ? <Settings size={18} /> : <><span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-accent-soft text-xs font-semibold text-accent">{name.slice(0, 2).toUpperCase()}</span><span className="truncate">{name}</span></>}</button>
        <button onClick={logout} aria-label="Sair" title="Sair" className={iconClass}><LogOut size={16} /></button>
      </div>
    </aside>
    {settings && <SettingsDialog onClose={() => setSettings(false)} />}
  </>;
}

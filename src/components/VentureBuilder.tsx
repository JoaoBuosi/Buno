import { memo, useEffect, useRef, useState } from "react";
import { Check, Download, LoaderCircle, Pause, Play, Sparkles } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import * as api from "../lib/api";
import type { VentureRun, VentureStatus, VentureSummary } from "../lib/api";

const stages = ["Produto e validação", "Arquitetura", "Plano de implementação", "Revisão e próximos passos"];
const labels: Record<VentureStatus, string> = {
  ready: "Pronto para iniciar", running: "Em andamento", paused: "Pausado",
  failed: "Etapa interrompida", awaiting_review: "Aguardando sua revisão", reviewed: "Revisado por você",
};
const button = "inline-flex items-center justify-center gap-2 rounded-lg border border-border px-3 py-2 text-sm text-text hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-50";
const message = (error: unknown) => error instanceof Error ? error.message : "Não foi possível concluir esta ação.";

const Document = memo(function Document({ content }: { content: string }) {
  return <div className="min-w-0 break-words text-sm leading-relaxed text-text [&_h1]:mb-3 [&_h1]:text-lg [&_h2]:my-3 [&_h2]:font-semibold [&_h3]:my-2 [&_h3]:font-semibold [&_p]:mb-3 [&_ul]:mb-3 [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:mb-3 [&_ol]:list-decimal [&_ol]:pl-5 [&_pre]:overflow-x-auto [&_pre]:rounded-lg [&_pre]:bg-bg [&_pre]:p-3 [&_code]:text-xs [&_table]:block [&_table]:overflow-x-auto [&_td]:border [&_td]:border-border [&_td]:p-2 [&_th]:border [&_th]:border-border [&_th]:p-2">
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={{
      a: ({ href, children }) => <a href={href} target="_blank" rel="noopener noreferrer" className="text-accent underline">{children}</a>,
      img: ({ alt }) => <span>[Imagem: {alt || "sem descrição"}]</span>,
    }}>{content}</ReactMarkdown>
  </div>;
});

export default function VentureBuilder({ projectId }: { projectId: string }) {
  const [runs, setRuns] = useState<VentureSummary[]>([]);
  const [run, setRun] = useState<VentureRun | null>(null);
  const [brief, setBrief] = useState("");
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [pending, setPending] = useState("");
  const [error, setError] = useState("");
  const [stage, setStage] = useState<number | null>(null);
  const [draft, setDraft] = useState("");
  const [templates, setTemplates] = useState<api.AgentTemplate[]>([]);
  const [templateId, setTemplateId] = useState("");
  const [notice, setNotice] = useState("");
  const controller = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const locked = loading || working || !!pending;

  useEffect(() => {
    const version = ++generation.current;
    const abort = new AbortController();
    controller.current = abort;
    async function load() {
      try {
        const [rows, catalog] = await Promise.all([api.listVentureRuns(projectId, abort.signal), api.getTemplates(abort.signal)]);
        const latest = rows[0] ? await api.getVentureRun(rows[0].id, abort.signal) : null;
        if (version !== generation.current) return;
        setRuns(rows); setRun(latest); setTemplates(catalog.items);
      } catch (cause) {
        if (!abort.signal.aborted && version === generation.current) setError(message(cause));
      } finally {
        if (version === generation.current) setLoading(false);
      }
    }
    void load();
    // This mutable ref tracks the latest request, not a DOM node. Cancel the current request on exit.
    // oxlint-disable-next-line react-hooks/exhaustive-deps
    return () => { generation.current++; controller.current?.abort(); };
  }, [projectId]);

  function remember(value: VentureRun) {
    setRun(value);
    setRuns(previous => [value, ...previous.filter(item => item.id !== value.id)]
      .sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, 50));
  }

  async function generate(value: VentureRun, version: number) {
    const abort = new AbortController();
    controller.current = abort;
    setWorking(true); setStage(value.next_step); setDraft(""); setError("");
    try {
      for await (const event of api.streamVentureRun(value.id, abort.signal)) {
        if (version !== generation.current) return;
        if (event.event === "start") setRun(previous => previous ? { ...previous, status: "running", error_message: null } : null);
        if (event.event === "stage") { setStage(event.data.index); setDraft(""); }
        if (event.event === "chunk") setDraft(previous => previous + event.data.text);
        if (event.event === "artifact") {
          setRun(previous => previous ? { ...previous, next_step: previous.next_step + 1, artifacts: [...previous.artifacts, event.data] } : null);
          setDraft("");
        }
        if (event.event === "error") setError(event.data.message);
        if (event.event === "done") setRun(previous => previous ? { ...previous, status: event.data.status } : null);
      }
    } catch (cause) {
      if (!abort.signal.aborted && version === generation.current) setError(message(cause));
    } finally {
      if (version === generation.current) {
        // Re-read durable checkpoints even when the connection ended between events.
        const refresh = new AbortController();
        controller.current = refresh;
        try { const saved = await api.getVentureRun(value.id, refresh.signal); if (version === generation.current) remember(saved); }
        catch (cause) { if (version === generation.current && !refresh.signal.aborted) setError(message(cause)); }
        if (version === generation.current) { setWorking(false); setStage(null); setDraft(""); }
      }
    }
  }

  async function create() {
    if (locked || brief.trim().length < 20) return;
    const version = ++generation.current;
    const abort = new AbortController(); controller.current = abort;
    setPending("create"); setError("");
    try {
      const value = await api.createVentureRun(projectId, brief.trim(), abort.signal, templateId);
      if (version !== generation.current) return;
      remember(value); setBrief("");
      await generate(value, version);
    } catch (cause) { if (version === generation.current && !abort.signal.aborted) setError(message(cause)); }
    finally { if (version === generation.current) setPending(""); }
  }

  async function select(id: string) {
    if (locked) return;
    const version = ++generation.current;
    const abort = new AbortController(); controller.current = abort;
    setPending("select"); setError("");
    try { const value = await api.getVentureRun(id, abort.signal); if (version === generation.current) remember(value); }
    catch (cause) { if (version === generation.current && !abort.signal.aborted) setError(message(cause)); }
    finally { if (version === generation.current) setPending(""); }
  }

  async function pause() {
    if (!run || pending === "pause") return;
    const version = generation.current;
    setPending("pause"); setError("");
    try {
      const saved = await api.pauseVentureRun(run.id);
      if (version !== generation.current) return;
      controller.current?.abort(); remember(saved);
    } catch (cause) { if (version === generation.current) setError(message(cause)); }
    finally { if (version === generation.current) setPending(""); }
  }

  async function review() {
    if (!run || locked) return;
    const version = generation.current; setPending("review"); setError("");
    try { const saved = await api.reviewVentureRun(run.id); if (version === generation.current) remember(saved); }
    catch (cause) { if (version === generation.current) setError(message(cause)); }
    finally { if (version === generation.current) setPending(""); }
  }

  async function download() {
    if (!run || locked) return;
    const version = generation.current; setPending("export"); setError("");
    try {
      const blob = await api.exportVentureRun(run.id);
      if (version !== generation.current) return;
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a"); link.href = url; link.download = `buno-plano-${run.id}.md`;
      document.body.append(link); link.click(); link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (cause) { if (version === generation.current) setError(message(cause)); }
    finally { if (version === generation.current) setPending(""); }
  }

  async function sharedAction(kind: "memory" | "rating", score = 5) {
    if (!run || locked) return;
    const version = generation.current; setPending(kind); setError(""); setNotice("");
    try {
      if (kind === "memory") await api.sharePlanKnowledge(projectId, run.id);
      else await api.ratePlan(projectId, run.id, score);
      if (version === generation.current) setNotice(kind === "memory" ? "Plano adicionado à memória do projeto." : "Avaliação de utilidade registrada.");
    } catch (cause) { if (version === generation.current) setError(message(cause)); }
    finally { if (version === generation.current) setPending(""); }
  }

  return <section aria-labelledby="venture-title" className="mb-8 rounded-2xl border border-border bg-surface p-4 md:p-6">
    <div className="mb-5 flex items-start gap-3">
      <Sparkles size={22} className="mt-1 shrink-0 text-accent" aria-hidden="true" />
      <div><h2 id="venture-title" className="text-lg font-semibold text-text">Venture Builder</h2>
        <p className="mt-1 max-w-2xl text-sm text-text-muted">Transforme uma ideia em um plano de produto, arquitetura e implementação, com uma revisão final.</p>
        <p className="mt-2 text-xs text-text-dim">Esta versão gera documentos para sua avaliação. Execução de código, testes e publicação ainda precisam ser feitas fora deste fluxo.</p>
      </div>
    </div>
    <form onSubmit={event => { event.preventDefault(); void create(); }} className="mb-6">
      <label className="mb-3 block text-sm text-text-muted">Template de especialistas
        <select value={templateId} disabled={locked} onChange={event => setTemplateId(event.target.value)} className="mt-1 block w-full rounded-lg border border-border bg-bg p-2 text-text">
          <option value="">Planejamento Buno</option>{templates.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
      </label>
      <label htmlFor="venture-brief" className="mb-2 block text-sm font-medium text-text">Qual produto você quer construir?</label>
      <textarea id="venture-brief" value={brief} onChange={event => setBrief(event.target.value)} required minLength={20} maxLength={6000} rows={4} disabled={locked}
        aria-describedby="venture-brief-help" placeholder="Descreva o problema, quem vai usar, as funções essenciais, seu orçamento e as tecnologias que prefere."
        className="w-full resize-y rounded-xl border border-border bg-bg p-3 text-sm text-text placeholder:text-text-dim disabled:opacity-60" />
      <div className="mt-2 flex flex-wrap items-center justify-between gap-3">
        <p id="venture-brief-help" className="text-xs text-text-dim">20 a 6.000 caracteres. As quatro etapas são geradas em sequência.</p>
        <button type="submit" disabled={locked || brief.trim().length < 20} className={`${button} bg-accent text-white hover:bg-accent-hover`}><Sparkles size={15} /> Criar planejamento</button>
      </div>
    </form>
    {error && <p role="alert" className="mb-4 rounded-lg bg-red-950/30 p-3 text-sm text-red-300">{error}</p>}
    {notice && <p role="status" className="mb-4 text-sm text-emerald-300">{notice}</p>}
    {loading && <p role="status" className="text-sm text-text-muted">Carregando planejamentos…</p>}
    {runs.length > 0 && <div className="mb-4">
      <label htmlFor="venture-history" className="mb-1 block text-xs text-text-muted">Planejamentos salvos — últimos 50</label>
      <select id="venture-history" value={run?.id ?? ""} disabled={locked} onChange={event => void select(event.target.value)} className="w-full rounded-lg border border-border bg-bg p-2 text-sm text-text disabled:opacity-60">
        {runs.map(value => <option key={value.id} value={value.id}>{new Date(value.created_at).toLocaleString("pt-BR")} · {labels[value.status]}</option>)}
      </select>
    </div>}
    {run && <div>
      <p className="mb-3 text-xs text-text-muted">Template: {run.template_snapshot.name || "Planejamento Buno"} · {run.reserved_tokens.toLocaleString("pt-BR")} tokens reservados · {run.knowledge_snapshot.length} referências compartilhadas. Os limites e o contexto deste plano são preservados nas retomadas.</p>
      <p className="mb-4 whitespace-pre-wrap break-words rounded-lg border border-border bg-bg p-3 text-sm text-text">{run.brief}</p>
      <ol className="mb-4 grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4" aria-label="Etapas do planejamento">
        {stages.map((title, index) => <li key={title} aria-current={working && stage === index ? "step" : undefined} className={`flex items-center gap-2 rounded-lg border p-3 text-xs ${index < run.next_step ? "border-emerald-800 text-emerald-300" : working && stage === index ? "border-accent text-text" : "border-border text-text-muted"}`}>
          {index < run.next_step ? <Check size={15} aria-hidden="true" /> : working && stage === index ? <LoaderCircle size={15} className="animate-spin" aria-hidden="true" /> : <span>{index + 1}.</span>}
          {title}{index < run.next_step && <span className="sr-only"> — concluída</span>}
        </li>)}
      </ol>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <p role="status" className="mr-auto text-sm text-text-muted">{labels[run.status]} · {run.next_step}/4 etapas salvas</p>
        {(working || run.status === "running") ? <button type="button" onClick={() => void pause()} disabled={pending === "pause" || pending === "select"} className={button}><Pause size={14} /> {pending === "pause" ? "Pausando…" : "Pausar"}</button> :
          ["ready", "paused", "failed"].includes(run.status) && <button type="button" onClick={() => void generate(run, ++generation.current)} disabled={locked} className={button}><Play size={14} /> {run.next_step === 0 ? "Iniciar" : "Retomar"}</button>}
        {run.artifacts.length > 0 && <button type="button" onClick={() => void download()} disabled={locked} className={button}><Download size={14} /> Baixar plano</button>}
        {run.status === "awaiting_review" && <button type="button" onClick={() => void review()} disabled={locked} className={button}><Check size={14} /> Marcar plano como revisado</button>}
      </div>
      {run.error_message && !error && <p className="mb-3 text-sm text-amber-200">{run.error_message}</p>}
      {run.status === "running" && !working && <p className="mb-3 text-sm text-amber-200">Esta execução foi iniciada em outro acesso ou perdeu a conexão. Pause para recuperar o controle, ou atualize para consultar o resultado. <button type="button" className="underline" disabled={locked} onClick={() => void select(run.id)}>Atualizar</button></p>}
      {working && <p className="mb-3 text-xs text-text-dim">Aguarde nesta tela. Ao sair, a geração pode ser interrompida; as etapas concluídas ficam salvas. A velocidade depende do modelo e do computador.</p>}
      {run.status === "awaiting_review" && <p className="mb-3 text-sm text-text-muted">Confira hipóteses, custos e decisões antes de implementar. Marcar como revisado registra sua leitura e não inicia outras ações.</p>}
      {run.status === "reviewed" && <div className="mb-4 flex flex-wrap items-center gap-2">
        <button type="button" disabled={locked} onClick={() => void sharedAction("memory")} className={button}>Compartilhar na memória do projeto</button>
        <label className="text-sm text-text-muted">Utilidade deste plano
          <select defaultValue="" disabled={locked} onChange={event => { if (event.target.value) void sharedAction("rating", Number(event.target.value)); }} className="ml-2 rounded-lg border border-border bg-bg p-2 text-text">
            <option value="" disabled>Avaliar</option>{[1, 2, 3, 4, 5].map(value => <option key={value} value={value}>{value}/5</option>)}
          </select>
        </label>
      </div>}
      <div className="space-y-3">
        {run.artifacts.map(artifact => <details key={`${run.id}-${artifact.key}`} open className="rounded-xl border border-border bg-bg p-4">
          <summary className="cursor-pointer text-sm font-semibold text-text">{artifact.title}</summary>
          <div className="mt-4"><Document content={artifact.content} /></div>
        </details>)}
        {working && stage !== null && <div className="rounded-xl border border-accent/50 p-4">
          <h3 className="mb-3 text-sm font-medium text-text">Gerando: {stages[stage]}</h3>
          <p className="whitespace-pre-wrap break-words text-sm text-text-muted">{draft || "Preparando a etapa…"}</p>
          <p className="mt-3 text-xs text-text-dim">Rascunho — será salvo ao concluir esta etapa.</p>
        </div>}
      </div>
    </div>}
  </section>;
}

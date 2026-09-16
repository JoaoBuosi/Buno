import { useEffect, useRef, type ChangeEvent, type KeyboardEvent } from "react";
import { ArrowUp, FileText, Loader2, Plus, Square, X } from "lucide-react";
export interface Attachment { id: string; filename: string; uploading?: boolean; note?: string | null }
interface Props {
  value: string; onChange: (value: string) => void; onSend: () => void;
  disabled: boolean; isStreaming?: boolean; onStop?: () => void;
  attachments: Attachment[]; onAttachFile: (file: File) => void; onRemoveAttachment: (id: string) => void;
}
export default function ChatInput({ value, onChange, onSend, disabled, isStreaming, onStop, attachments, onAttachFile, onRemoveAttachment }: Props) {
  const textarea = useRef<HTMLTextAreaElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const busy = disabled || attachments.some(a => a.uploading);
  useEffect(() => {
    if (textarea.current) { textarea.current.style.height = "auto"; textarea.current.style.height = `${Math.min(textarea.current.scrollHeight, 160)}px`; }
  }, [value]);
  function keyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault(); if (value.trim() && !busy) onSend();
    }
  }
  function selectFile(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]; if (file) onAttachFile(file); e.target.value = "";
  }
  return <div className="rounded-2xl border border-border bg-surface p-3 shadow-xl shadow-black/10 focus-within:border-accent/60">
    {attachments.length > 0 && <div className="mb-3 flex flex-wrap gap-2" aria-label="Arquivos desta conversa">
      {attachments.map(a => <div key={a.id} className="flex max-w-full items-center gap-2 rounded-lg border border-border bg-surface-hover px-2.5 py-2 text-xs" title={a.note || a.filename}>
        {a.uploading ? <Loader2 size={14} className="animate-spin text-text-muted" /> : <FileText size={14} className="shrink-0 text-accent" />}
        <span className="max-w-44 truncate text-text">{a.filename}</span>
        {a.note && <span aria-label={a.note} className="text-amber-300">!</span>}
        <button disabled={busy} onClick={() => onRemoveAttachment(a.id)} aria-label={`Remover ${a.filename}`} className="text-text-muted hover:text-red-400 disabled:opacity-30"><X size={14} /></button>
      </div>)}
    </div>}
    <textarea ref={textarea} value={value} onChange={e => onChange(e.target.value)} onKeyDown={keyDown}
      aria-label="Mensagem para a Buno" placeholder="Pergunte à Buno ou envie um arquivo…" rows={2} maxLength={8000}
      className="max-h-40 w-full resize-none bg-transparent px-1 py-1 text-sm leading-6 text-text outline-none placeholder:text-text-muted" />
    <div className="mt-2 flex items-center justify-between">
      <input ref={fileInput} type="file" className="hidden" onChange={selectFile} accept=".pdf,.docx,.txt,.md,.csv,.json,.py,.js,.ts,.tsx,.jsx,.html,.css,.yaml,.yml,.xml,.sql,.png,.jpg,.jpeg,.webp" />
      <button type="button" disabled={busy} onClick={() => fileInput.current?.click()} aria-label="Anexar arquivo" title="Anexar documento ou imagem" className="flex h-9 items-center gap-2 rounded-lg px-2 text-xs text-text-muted hover:bg-surface-hover hover:text-text disabled:opacity-30"><Plus size={18} />Anexar</button>
      <div className="flex items-center gap-3">
        {value.length > 7000 && <span className="text-xs text-text-muted">{value.length}/8000</span>}
        <button type="button" onClick={isStreaming ? onStop : onSend} disabled={!isStreaming && (busy || !value.trim())}
          aria-label={isStreaming ? "Parar resposta" : "Enviar mensagem"} title={isStreaming ? "Parar resposta" : "Enviar mensagem"}
          className="grid h-9 w-9 place-items-center rounded-xl bg-accent text-white transition hover:bg-accent-hover disabled:opacity-30">
          {isStreaming ? <Square size={14} fill="currentColor" /> : <ArrowUp size={19} />}
        </button>
      </div>
    </div>
  </div>;
}

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { lazy, Suspense } from "react";
import { Check, Copy, Pencil } from "lucide-react";
const CodeBlock = lazy(() => import("./CodeBlock"));

interface MessageBubbleProps {
  id?: string;
  role: "user" | "assistant" | "system";
  content: string;
  disabled?: boolean;
  onEdit?: (id: string, content: string) => void;
}

export default function MessageBubble({ id, role, content, disabled = false, onEdit }: MessageBubbleProps) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(content);
    } catch {
      const area = document.createElement("textarea");
      area.value = content; area.setAttribute("readonly", ""); area.style.position = "fixed"; area.style.opacity = "0";
      document.body.appendChild(area); area.select(); document.execCommand("copy"); area.remove();
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1400);
  }

  if (role === "user") {
    return (
      <div className="flex flex-col items-end">
        <div className="max-w-[90%] whitespace-pre-wrap break-words rounded-2xl bg-surface px-4 py-2.5 text-sm text-text">
          {content}
        </div>
        <div className="mt-1 flex items-center gap-1 pr-1 text-text-muted">
          <button type="button" onClick={() => void copy()} disabled={disabled} aria-label={copied ? "Mensagem copiada" : "Copiar mensagem"} title={copied ? "Copiado" : "Copiar"} className="rounded-md p-1.5 transition hover:bg-surface-hover hover:text-text disabled:opacity-30">
            {copied ? <Check size={14} className="text-emerald-400" /> : <Copy size={14} />}
          </button>
          {id && onEdit && <button type="button" onClick={() => onEdit(id, content)} disabled={disabled} aria-label="Editar mensagem" title="Editar" className="rounded-md p-1.5 transition hover:bg-surface-hover hover:text-text disabled:opacity-30"><Pencil size={14} /></button>}
        </div>
      </div>
    );
  }

  return (
    <div className="min-w-0 max-w-full break-words text-sm leading-relaxed text-text">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          code(props) {
            const { className, children } = props;
            const match = /language-(\w+)/.exec(className || "");
            const isInline = !match && !String(children).includes("\n");

            if (isInline) {
              return (
                <code className="rounded bg-surface px-1.5 py-0.5 text-[13px] text-text">
                  {children}
                </code>
              );
            }

            return (
              <Suspense fallback={<pre className="overflow-auto rounded-lg bg-surface p-3">{children}</pre>}><CodeBlock
                language={match?.[1] || ""}
                code={String(children).replace(/\n$/, "")}
              /></Suspense>
            );
          },
          p({ children }) {
            return <p className="mb-3 last:mb-0">{children}</p>;
          },
          ul({ children }) {
            return <ul className="mb-3 list-disc pl-5">{children}</ul>;
          },
          ol({ children }) {
            return <ol className="mb-3 list-decimal pl-5">{children}</ol>;
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

import { useState } from "react";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";
import { Check, Copy } from "lucide-react";

interface CodeBlockProps {
  language: string;
  code: string;
}

export default function CodeBlock({ language, code }: CodeBlockProps) {
  const [copied, setCopied] = useState(false);

  const [error, setError] = useState(false);
  async function handleCopy() {
    try { await navigator.clipboard.writeText(code); setCopied(true); setError(false); setTimeout(() => setCopied(false), 1500); }
    catch { setError(true); }
  }

  return (
    <div className="my-2 overflow-hidden rounded-lg border border-border">
      <div className="flex items-center justify-between bg-surface px-3 py-1.5 text-xs text-text-muted">
        <span>{language || "text"}</span>
        <button
          onClick={handleCopy}
          className="flex items-center gap-1 hover:text-text"
        >
          {copied ? <Check size={13} /> : <Copy size={13} />}
          {copied ? "Copiado" : "Copiar"}
        </button>
      </div>
      {error && <p role="status" className="px-3 py-2 text-xs text-text-muted">Não foi possível copiar. Selecione o código e copie manualmente.</p>}
      <SyntaxHighlighter
        language={language}
        style={oneDark}
        customStyle={{
          margin: 0,
          padding: "12px 14px",
          background: "#141419",
          fontSize: "13px",
        }}
      >
        {code}
      </SyntaxHighlighter>
    </div>
  );
}

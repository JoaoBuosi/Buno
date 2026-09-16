const PHASE_LABELS: Record<string, string> = {
  connecting: "Conectando...",
  searching_web: "Pesquisando na web...",
  searching_context: "Pesquisando contexto...",
  generating: "Sintetizando resposta...",
};

interface LoadingBubbleProps {
  phase: string;
  elapsedMs: number;
}

export default function LoadingBubble({ phase, elapsedMs }: LoadingBubbleProps) {
  const label = PHASE_LABELS[phase] ?? "Pensando...";
  const seconds = (elapsedMs / 1000).toFixed(1);

  return (
    <div className="flex items-center gap-3 text-sm text-text-muted">
      <div className="flex gap-1">
        <span
          className="h-2 w-2 animate-pulse rounded-full bg-accent"
          style={{ animationDelay: "0ms" }}
        />
        <span
          className="h-2 w-2 animate-pulse rounded-full bg-accent"
          style={{ animationDelay: "200ms" }}
        />
        <span
          className="h-2 w-2 animate-pulse rounded-full bg-accent"
          style={{ animationDelay: "400ms" }}
        />
      </div>
      <span>{label}</span>
      <span className="text-text-dim tabular-nums">· {seconds}s</span>
    </div>
  );
}

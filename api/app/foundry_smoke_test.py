"""Smoke test de ponta a ponta: cria e chama um agente real no Foundry."""

from __future__ import annotations

import argparse
import asyncio
import sys

from app.services.foundry_provider import FoundryConfigurationError, FoundryProviderError, run_agent_task


DEFAULT_TASK = (
    "Analise esta tarefa da Buno e responda em até cinco linhas: proponha um MVP de "
    "atendimento com IA para uma pizzaria, com um critério de sucesso mensurável."
)


async def main(task: str) -> int:
    try:
        result = await run_agent_task(task)
    except (FoundryConfigurationError, FoundryProviderError, ValueError) as exc:
        print(f"[ERRO] {exc}", file=sys.stderr)
        return 1
    print("[OK] Agente executado no Microsoft Foundry")
    print(f"Agente: {result.agent_name} (versão {result.agent_version or 'n/d'})")
    print(f"Conversa: {result.conversation_id}")
    print("\nResultado:\n" + result.output_text)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Executa uma tarefa real com um agente Microsoft Foundry")
    parser.add_argument("--tarefa", default=DEFAULT_TASK, help="Texto da tarefa a enviar ao agente")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.tarefa)))

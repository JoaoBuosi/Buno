#!/usr/bin/env python3
"""Comandos locais da Buno. Execute `python buno.py --help`."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
API = ROOT / "api"
WEB = ROOT / "web"


class SetupError(Exception):
    pass


def api_python() -> Path:
    return API / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def run(command: list[str], cwd: Path, *, check: bool = True) -> int:
    result = subprocess.run(command, cwd=cwd)
    if check and result.returncode:
        raise SetupError("O comando anterior falhou. Corrija o erro indicado antes de continuar.")
    return result.returncode


def node_executable() -> str:
    node = shutil.which("node")
    if not node:
        raise SetupError("Node.js não encontrado. Instale o Node.js 24 e reabra o terminal.")
    try:
        result = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=10, check=True)
        major = int(result.stdout.strip().lstrip("v").split(".")[0])
    except (OSError, ValueError, subprocess.SubprocessError):
        raise SetupError("Não foi possível verificar o Node.js. Confira a instalação.") from None
    if major < 24:
        raise SetupError("Use Node.js 24 ou superior para esta versão da Buno.")
    return node


def npm_command(node: str) -> list[str]:
    # Invoke npm through node, avoiding .cmd shell quoting on Windows.
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    candidates = [Path(node).resolve().parent / "node_modules/npm/bin/npm-cli.js"]
    if npm:
        resolved = Path(npm).resolve()
        if resolved.suffix == ".js":
            candidates.append(resolved)
        candidates.append(Path(npm).parent / "node_modules/npm/bin/npm-cli.js")
    for candidate in candidates:
        if candidate.is_file():
            return [node, str(candidate)]
    raise SetupError("npm não encontrado na instalação do Node.js. Reinstale o Node.js com npm.")


def create_local_config(api_dir: Path = API) -> bool:
    """Create configuration once, preserving any existing user's configuration."""
    target = api_dir / ".env"
    if target.exists():
        return False
    template = (api_dir / ".env.example").read_text(encoding="utf-8")
    marker = "JWT_SECRET=substitua-por-um-segredo-aleatorio"
    if marker not in template:
        raise SetupError("O exemplo de configuração está incompleto. Confira api/.env.example.")
    content = template.replace(marker, f"JWT_SECRET={secrets.token_urlsafe(48)}")
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return False
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
        output.write(content)
    return True


def require_api() -> Path:
    executable = api_python()
    if not executable.is_file():
        raise SetupError("Prepare o projeto primeiro: python buno.py preparar")
    if not (API / ".env").is_file():
        raise SetupError("Falta api/.env. Execute: python buno.py preparar")
    return executable


def prepare() -> int:
    node = node_executable()
    npm = npm_command(node)
    if not api_python().is_file():
        print("Criando o ambiente Python…", flush=True)
        run([sys.executable, "-m", "venv", str(API / ".venv")], ROOT)
    print("Instalando as dependências da API…", flush=True)
    run([str(api_python()), "-m", "pip", "install", "-r", "requirements.txt"], API)
    print("Instalando as dependências da interface…", flush=True)
    run(npm + ["ci"], WEB)
    if create_local_config():
        print("api/.env criado com um segredo novo. Confira a configuração do banco e do Ollama.")
    else:
        print("Sua configuração existente em api/.env foi preservada.")
    print("Preparação concluída. Próximo comando: python buno.py diagnostico")
    return 0


def diagnose(*, generate: bool = False, json_output: bool = False) -> int:
    executable = require_api()
    command = [str(executable), "-m", "app.diagnostics"]
    if generate:
        command.append("--gerar")
    if json_output:
        command.append("--json")
    return run(command, API, check=False)


def check_ports(ports: tuple[int, ...] = (8000, 5173)) -> None:
    for port in ports:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                raise SetupError(f"A porta {port} já está em uso ou indisponível. Feche a outra instância da Buno antes de iniciar.") from None


def stop_processes(processes: list[subprocess.Popen]) -> None:
    """Stop only the process groups created by this launcher."""
    for process in processes:
        if process.poll() is not None:
            continue
        try:
            if os.name == "nt":
                process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                os.killpg(process.pid, signal.SIGTERM)
        except OSError:
            process.terminate()
    for process in processes:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def start() -> int:
    executable = require_api()
    node = node_executable()
    vite = WEB / "node_modules/vite/bin/vite.js"
    if not vite.is_file():
        raise SetupError("Faltam as dependências da interface. Execute: python buno.py preparar")
    check_ports()
    print("Conferindo banco e modelos antes de iniciar…", flush=True)
    if diagnose():
        raise SetupError("Corrija os itens [ERRO] do diagnóstico e execute iniciar novamente.")
    processes = []
    options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    try:
        processes.append(subprocess.Popen([str(executable), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"], cwd=API, **options))
        processes.append(subprocess.Popen([node, str(vite), "--host", "127.0.0.1", "--port", "5173", "--strictPort"], cwd=WEB, **options))
        print("\nIniciando Buno: http://127.0.0.1:5173\nAPI: http://127.0.0.1:8000/docs\nMantenha este terminal aberto. Ctrl+C encerra os dois serviços.\n", flush=True)
        while all(process.poll() is None for process in processes):
            time.sleep(.3)
        raise SetupError("Um dos serviços encerrou. Confira a mensagem acima; os dois foram parados.")
    except KeyboardInterrupt:
        print("\nEncerrando a Buno…")
        return 0
    finally:
        stop_processes(processes)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Configure, confira e inicie sua Buno local.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("preparar", help="Instala dependências e cria api/.env somente se ele não existe")
    diagnostic = commands.add_parser("diagnostico", help="Confere configuração, banco, migrações e modelos")
    diagnostic.add_argument("--gerar", action="store_true", help="Também gera uma resposta curta e um embedding reais (pode levar até 4 minutos)")
    diagnostic.add_argument("--json", action="store_true", help="Imprime resultado estruturado sem credenciais")
    commands.add_parser("banco-local", help="Inicia apenas o PostgreSQL local do Docker Compose")
    commands.add_parser("migrar", help="Aplica as migrações ao banco definido em api/.env")
    commands.add_parser("iniciar", help="Confere dependências e inicia a API e o frontend juntos")
    commands.add_parser("cofre-iniciar", help="Cria a chave mestra local do cofre sem sobrescrever uma chave existente")
    foundry = commands.add_parser("foundry-smoke-test", help="Cria e executa uma tarefa real com um agente Microsoft Foundry")
    foundry.add_argument("--tarefa", default=None, help="Texto da tarefa; se omitido, usa um exemplo seguro da Buno")
    args = parser.parse_args(argv)
    if sys.version_info < (3, 12):
        print("[ERRO] Use Python 3.12 ou superior.")
        return 1
    try:
        if args.command == "preparar":
            return prepare()
        if args.command == "diagnostico":
            return diagnose(generate=args.gerar, json_output=args.json)
        if args.command == "banco-local":
            docker = shutil.which("docker")
            if not docker:
                raise SetupError("Docker não encontrado. Abra/instale Docker Desktop ou configure um banco existente em api/.env.")
            return run([docker, "compose", "-f", str(ROOT / "compose.yaml"), "up", "-d", "--wait", "--wait-timeout", "60", "db"], ROOT)
        if args.command == "migrar":
            return run([str(require_api()), "-m", "alembic", "upgrade", "head"], API)
        if args.command == "cofre-iniciar":
            return run([str(require_api()), "-m", "app.vault_setup"], API)
        if args.command == "foundry-smoke-test":
            command = [str(require_api()), "-m", "app.foundry_smoke_test"]
            if args.tarefa:
                command += ["--tarefa", args.tarefa]
            return run(command, API, check=False)
        return start()
    except SetupError as exc:
        print(f"[ERRO] {exc}", file=sys.stderr)
        return 1
    except OSError:
        print("[ERRO] Não foi possível executar um programa ou acessar um arquivo. Confira instalação e permissões.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nOperação interrompida.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

from datetime import datetime, timezone


class ConnectionManager:
    """
    Guarda em memória o último status conhecido da conexão com o provedor de IA.
    Simples de propósito: um processo FastAPI, um estado. Se escalar pra múltiplas
    instâncias depois, isso pode virar uma chave no Redis em vez de estado local.
    """

    def __init__(self) -> None:
        self._connected: bool = True
        self._last_error: str | None = None
        self._updated_at: datetime = datetime.now(timezone.utc)

    def mark_ok(self) -> None:
        self._connected = True
        self._last_error = None
        self._updated_at = datetime.now(timezone.utc)

    def mark_error(self, error: str) -> None:
        self._connected = False
        self._last_error = error
        self._updated_at = datetime.now(timezone.utc)

    @property
    def status(self) -> dict:
        return {
            "connected": self._connected,
            "last_error": self._last_error,
            "updated_at": self._updated_at.isoformat(),
        }


# instância única reutilizada pela aplicação inteira
connection_manager = ConnectionManager()

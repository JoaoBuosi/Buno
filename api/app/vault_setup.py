"""Create the configured vault key once. Never print or overwrite key material."""
import base64
import os
from pathlib import Path
from app.core.config import settings


def initialize(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return False
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(base64.b64encode(os.urandom(32)) + b"\n")
    return True


if __name__ == "__main__":
    created = initialize(Path(settings.VAULT_KEY_FILE))
    print("Chave do cofre criada. Guarde um backup separado do banco e restrinja o acesso ao arquivo." if created
          else "A chave existente foi preservada. Não a substitua: as credenciais dependem dela.")

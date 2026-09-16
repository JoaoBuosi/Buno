import base64
import hashlib
import os
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag
from fastapi import HTTPException
from app.core.config import settings
from app.models.governance import VaultSecret
from app.services.governance_service import scoped_row, audit


def read_key():
    try:
        key = base64.b64decode(Path(settings.VAULT_KEY_FILE).read_bytes().strip(), validate=True)
        if len(key) != 32:
            raise ValueError()
        return key
    except (OSError, ValueError):
        raise HTTPException(503, "Cofre indisponível. Configure a chave mestra no servidor.") from None


def vault_ready():
    try:
        read_key()
        return True
    except HTTPException:
        return False


def aad(user_id, project_id, secret_id):
    return f"buno-vault-v1:{user_id}:{project_id}:{secret_id}".encode()


def encrypt(value, user_id, project_id, secret_id):
    key = read_key()
    nonce = os.urandom(12)
    encrypted = AESGCM(key).encrypt(nonce, value.encode(), aad(user_id, project_id, secret_id))
    return base64.b64encode(nonce + encrypted).decode(), hashlib.sha256(key).hexdigest()[:16]


async def resolve_for_tool(db, user_id, project_id, secret_id, role, tool):
    """For trusted backend tools only. Do not pass the result to an LLM or browser."""
    row = await scoped_row(db, VaultSecret, user_id, project_id, secret_id)
    if row.revoked_at or role not in row.allowed_roles or tool not in row.allowed_tools:
        raise HTTPException(403, "Esta ferramenta não tem acesso à credencial")
    key = read_key()
    try:
        raw = base64.b64decode(row.ciphertext, validate=True)
        value = AESGCM(key).decrypt(raw[:12], raw[12:], aad(user_id, project_id, secret_id)).decode()
    except (InvalidTag, ValueError, UnicodeError):
        raise HTTPException(503, "Não foi possível abrir a credencial com a chave configurada") from None
    audit(db, user_id, project_id, "vault.used", "Credencial acessada por ferramenta autorizada.",
          details={"secret_id": str(row.id), "role": role, "tool": tool})
    return value

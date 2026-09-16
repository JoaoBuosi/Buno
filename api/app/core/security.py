import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
import bcrypt
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.models.user import User

from app.core.config import settings



# tokenUrl só documenta pro Swagger onde pegar o token — o endpoint em si
# (/auth/login) ainda vai ser implementado no próximo passo.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/auth/login")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        # Preserva a verificação de hashes bcrypt antigos gerados pelo passlib.
        return bcrypt.checkpw(plain_password.encode("utf-8")[:72], hashed_password.encode("ascii"))
    except (ValueError, UnicodeError):
        return False


def create_access_token(user_id: uuid.UUID) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    payload = {"sub": str(user_id), "exp": expire}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


async def get_current_user_id(token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)) -> uuid.UUID:
    """Decodifica o JWT do header Authorization e devolve o id do usuário logado."""
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Não foi possível validar as credenciais",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            raise credentials_error
        parsed_id = uuid.UUID(user_id)
        if "exp" not in payload:
            raise credentials_error
    except (JWTError, ValueError, TypeError, AttributeError):
        raise credentials_error
    if await db.get(User, parsed_id) is None:
        raise credentials_error
    return parsed_id

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings


def _to_async_url(url: str) -> str:
    """
    O Alembic (migrations) continua usando driver síncrono (psycopg2) — só a
    aplicação em si precisa do driver assíncrono (asyncpg). Essa função troca
    o dialeto na URL sem exigir que você mantenha duas variáveis no .env.
    """
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql+psycopg2://"):
        return url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
    return url


from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

connection_url = make_url(_to_async_url(settings.DATABASE_URL))
connect_args = {}
if connection_url.drivername.startswith("postgresql"):
    query = dict(connection_url.query)
    ssl_mode = query.pop("sslmode", None)
    query.pop("channel_binding", None)
    if ssl_mode:
        connect_args["ssl"] = ssl_mode
    connect_args.update(statement_cache_size=0, prepared_statement_cache_size=0)
    connection_url = connection_url.set(query=query)
engine = create_async_engine(connection_url, pool_pre_ping=True, poolclass=NullPool, connect_args=connect_args)

AsyncSessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)


async def get_db():
    """Dependência do FastAPI: abre uma sessão assíncrona por request e garante que fecha."""
    async with AsyncSessionLocal() as session:
        yield session

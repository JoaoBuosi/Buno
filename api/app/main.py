from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

# Importa app.db.base ANTES de qualquer outra coisa: esse módulo importa todos
# os models (User, Conversation, Message, Memory) de uma vez, garantindo que o
# SQLAlchemy conhece todas as relações entre eles antes da primeira query —
# sem isso, dependendo de qual endpoint for chamado primeiro, models que só
# são importados "de leve" (via outro serviço) podem não estar registrados
# ainda quando o mapper tenta resolver uma relationship() por nome de string.
from app.db import base as _register_all_models  # noqa: F401

from app.api.v1.router import api_router
from app.core.config import settings
from app.services.connection_manager import connection_manager

app = FastAPI(title="Buno API", version="0.10.0")


@app.exception_handler(RequestValidationError)
async def safe_validation_error(request, exc):
    # Do not echo submitted credentials (including invalid vault values) in errors.
    return JSONResponse(status_code=422, content={"detail": [
        {"loc": list(item["loc"]), "msg": item["msg"], "type": item["type"]} for item in exc.errors()
    ]})

# Configure em CORS_ORIGINS as origens que devem acessar a API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")


@app.get("/api/v1/health")
def health() -> dict:
    return {"api": "ok", "provider": connection_manager.status}

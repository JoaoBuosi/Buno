from fastapi import APIRouter

from app.api.v1.endpoints import agents, auth, chat, conversations, documents, projects, memories, venture, governance

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
api_router.include_router(
    conversations.router, prefix="/conversations", tags=["conversations"]
)
api_router.include_router(projects.router, prefix="/projects", tags=["projects"])
api_router.include_router(agents.router, prefix="/agents", tags=["agents"])
api_router.include_router(documents.router, prefix="/documents", tags=["documents"])

api_router.include_router(memories.router, prefix="/memories", tags=["memories"])

api_router.include_router(venture.router, prefix="/venture", tags=["venture"])
api_router.include_router(governance.router, prefix="/governance", tags=["governance"])

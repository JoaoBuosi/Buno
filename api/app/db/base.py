# Importa todos os models aqui para que o Alembic (autogenerate) consiga enxergá-los
# através do Base.metadata. Não é usado diretamente no código, só na hora da migration.

from app.db.base_class import Base  # noqa
from app.models.user import User  # noqa
from app.models.project import Project  # noqa
from app.models.conversation import Conversation  # noqa
from app.models.message import Message  # noqa
from app.models.memory import Memory  # noqa
from app.models.document import Document  # noqa
from app.models.document_chunk import DocumentChunk  # noqa

from app.models.venture_run import VentureRun  # noqa
from app.models.governance import ProjectPolicy, AuditEvent, UsageSpan, Approval, VaultSecret, KnowledgeNote, KnowledgeEdge, AgentTemplate, RunRating  # noqa
from app.models.agent import Agent, AgentActivity  # noqa

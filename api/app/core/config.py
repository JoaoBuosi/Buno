from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Banco de dados (Supabase, Neon, etc.)
    DATABASE_URL: str  # ex: postgresql+psycopg2://user:pass@host:5432/dbname?sslmode=require

    # Provedor de IA (fica escondido, o front nunca vê isso) — Ollama local
    # sem depender de nenhuma API externa, sem key, sem cota.
    PROVIDER_API_KEY: str = ""  # não usado pelo Ollama, mantido pra compatibilidade
    PROVIDER_BASE_URL: str = "http://localhost:11434"
    PROVIDER_CHAT_MODEL: str = "qwen3.5:9b"
    PROVIDER_EMBEDDING_MODEL: str = "nomic-embed-text"
    EMBEDDING_DIMENSIONS: int = 768  # dimensão nativa do nomic-embed-text

    # Resiliência (v0.3) — inferência local pode ser lenta no cold start,
    # então os timeouts são bem mais generosos que os de uma API na nuvem.
    PROVIDER_CONNECT_TIMEOUT: float = 10.0   # segundos pra abrir a conexão
    PROVIDER_READ_TIMEOUT: float = 300.0     # segundos esperando tokens (5 min)
    PROVIDER_MAX_RETRIES: int = 3            # tentativas de conexão antes de desistir
    PROVIDER_RETRY_BACKOFF_SECONDS: float = 1.0  # multiplicado pelo nº da tentativa
    # Limite de tokens gerados por resposta — evita respostas longas demais que
    # sozinhas estourariam qualquer expectativa de tempo de resposta.
    PROVIDER_MAX_TOKENS: int = 1500
    # Orçamento de tokens pro histórico + memória mandados como contexto ao modelo
    # (separado do PROVIDER_MAX_TOKENS, que é o limite da RESPOSTA gerada).
    PROVIDER_CONTEXT_TOKEN_BUDGET: int = 4000

    # Web RAG (v0.4) — busca web em tempo real via Tavily
    TAVILY_API_KEY: str = ""
    WEB_SEARCH_MAX_RESULTS: int = 5
    WEB_SEARCH_TIMEOUT: float = 15.0

    # Upload de documentos (v0.5)
    UPLOAD_DIR: str = "uploads"
    MAX_UPLOAD_SIZE_MB: int = 20
    # tamanho de cada pedaço do documento em CARACTERES (não tokens — mesma
    # aproximação simples que já usamos no trim_history_to_token_budget)
    DOCUMENT_CHUNK_SIZE: int = 1500
    DOCUMENT_CHUNK_OVERLAP: int = 200
    RELEVANT_DOCUMENT_CHUNKS_LIMIT: int = 5

    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000"]
    MAX_MESSAGE_CHARS: int = Field(default=8000, ge=1, le=64000)
    MEMORY_LOOKUP_TIMEOUT: float = Field(default=3, gt=0)
    MEMORY_WRITE_TIMEOUT: float = Field(default=20, gt=0)
    CONTEXT_LOOKUP_TIMEOUT: float = Field(default=8, gt=0)
    DOCUMENT_PROCESS_TIMEOUT: float = Field(default=20, gt=0)
    DOCUMENT_MAX_TEXT_CHARS: int = Field(default=120000, ge=1000)
    DOCUMENT_MAX_CHUNKS: int = Field(default=64, ge=1, le=256)
    MAX_IMAGES_PER_CHAT: int = Field(default=4, ge=1, le=8)
    CHAT_REQUESTS_PER_MINUTE: int = Field(default=20, ge=1)

    @model_validator(mode="after")
    def valid_limits(self):
        if not 0 <= self.DOCUMENT_CHUNK_OVERLAP < self.DOCUMENT_CHUNK_SIZE:
            raise ValueError("DOCUMENT_CHUNK_OVERLAP deve ser menor que DOCUMENT_CHUNK_SIZE")
        if self.MAX_MESSAGE_CHARS > self.PROVIDER_CONTEXT_TOKEN_BUDGET * 4 - 1000:
            raise ValueError("O orçamento de contexto precisa comportar a mensagem e as instruções")
        if "*" in self.CORS_ORIGINS:
            raise ValueError("CORS_ORIGINS precisa das origens exatas do frontend")
        return self

    VENTURE_STEP_TIMEOUT_SECONDS: float = Field(default=180, gt=0, le=600)
    VENTURE_MAX_OUTPUT_CHARS: int = Field(default=12000, ge=1000, le=32000)
    VAULT_KEY_FILE: str = "secrets/vault.key"
    KNOWLEDGE_EMBED_TIMEOUT: float = Field(default=5, gt=0, le=30)

    # Microsoft Foundry (v0.10) — desativado até o usuário configurar o projeto
    # no Azure. A autenticação usa DefaultAzureCredential (az login localmente).
    FOUNDRY_ENABLED: bool = False
    FOUNDRY_PROJECT_ENDPOINT: str = ""
    FOUNDRY_MODEL: str = ""
    FOUNDRY_AGENT_NAME: str = "BunoSmokeAgent"
    FOUNDRY_AGENT_INSTRUCTIONS: str = (
        "Você é o agente de validação da Buno. Execute a tarefa solicitada com clareza, "
        "declare limitações e devolva um resultado verificável em texto."
    )
    FOUNDRY_TIMEOUT_SECONDS: float = Field(default=120, gt=0, le=600)

    # Auth
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60 * 24  # 1 dia

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()

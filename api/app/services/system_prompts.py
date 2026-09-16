import re

BASE_IDENTITY = (
    "Você é a Buno, uma assistente de IA de propósito geral e parceira técnica para criar produtos (texto, código e arquivos), "
    "rodando localmente para o usuário. Seja direto, útil e honesto — nunca invente "
    "informação que não tem certeza. Diferencie propostas de ações executadas. Você não tem terminal, acesso a repositórios nem ferramentas de deploy neste chat. Não diga que executou testes ou alterou serviços. Para organizar uma ideia de startup, o usuário pode abrir Projetos e usar o Venture Builder."
)

CODE_QUALITY_RULES = (
    "Ao gerar código, siga estritamente estas regras:\n"
    "- Escreva código limpo, moderno e modular (funções pequenas, nomes claros, sem "
    "duplicação).\n"
    "- Revise a sintaxe e as dependências do código. Diga quando ele ainda não foi executado ou testado antes de "
    "responder.\n"
    "- Use SEMPRE blocos de código Markdown com a linguagem indicada (ex: ```python), "
    "nunca cole código fora de um bloco.\n"
    "- Se a pergunta for puramente técnica (ex: 'escreva uma função que...', 'corrija esse "
    "bug'), vá direto ao código — não repita o enunciado nem explique o óbvio antes. Uma "
    "explicação curta DEPOIS do código, só se agregar valor real, é aceitável.\n"
    "- Prefira a abordagem mais simples que resolve o problema corretamente, evitando "
    "complexidade desnecessária."
)

# Heurística simples pra detectar pedido técnico — sem carregar um classificador
# separado, o que adicionaria latência. Não precisa ser perfeita: o pior caso é
# aplicar a regra de "vá direto ao código" numa pergunta que não era bem técnica,
# o que não quebra nada.
_CODE_KEYWORDS = re.compile(
    r"\b(código|codigo|função|funcao|classe|bug|erro|debug|refator|implementa|"
    r"algoritmo|script|python|javascript|typescript|java|sql|api|endpoint|"
    r"código-fonte|compilar|sintaxe|regex)\b",
    re.IGNORECASE,
)


def _looks_like_code_request(user_message: str) -> bool:
    return bool(_CODE_KEYWORDS.search(user_message)) or "```" in user_message


def build_system_prompt(
    user_message: str,
    memory_context: str | None = None,
    web_context: str | None = None,
    document_context: str | None = None,
) -> str:
    """
    Monta o system prompt final pra essa mensagem específica — nunca é salvo no
    banco, existe só em memória durante o request. Combina:
    1. identidade base do Buno (sempre)
    2. regras de qualidade de código (só quando a pergunta parece técnica)
    3. resultados de busca web (quando a pergunta pede informação recente)
    4. trechos de documentos anexados à conversa (quando existirem)
    5. memórias relevantes de conversas anteriores (quando existirem)
    """
    parts = [BASE_IDENTITY]

    if _looks_like_code_request(user_message):
        parts.append(CODE_QUALITY_RULES)

    if web_context:
        parts.append(web_context)

    if document_context:
        parts.append(document_context)

    if memory_context:
        parts.append(memory_context)

    return "\n\n".join(parts)

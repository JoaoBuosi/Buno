from io import BytesIO

import docx
from pypdf import PdfReader

# Tipos que sabemos ler como texto puro (código, markdown, dados, etc.)
_PLAIN_TEXT_EXTENSIONS = {
    ".txt", ".md", ".csv", ".json", ".py", ".js", ".ts", ".tsx", ".jsx",
    ".html", ".css", ".yaml", ".yml", ".xml", ".sql", ".sh", ".java",
    ".c", ".cpp", ".go", ".rs", ".log",
}


def _extract_pdf(data: bytes) -> str:
    reader = PdfReader(BytesIO(data))
    return "\n\n".join(page.extract_text() or "" for page in reader.pages)


def _extract_docx(data: bytes) -> str:
    document = docx.Document(BytesIO(data))
    return "\n".join(p.text for p in document.paragraphs)


def _extract_plain_text(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def extract_text(filename: str, content_type: str, data: bytes) -> str | None:
    """
    Tenta extrair texto do arquivo. Devolve None quando não sabemos ler esse
    tipo (ex: imagem, binário qualquer) — o arquivo ainda fica salvo, só não
    vira contexto pro chat.
    """
    lower_name = filename.lower()

    if lower_name.endswith(".pdf") or content_type == "application/pdf":
        return _extract_pdf(data)

    if lower_name.endswith(".docx") or content_type in (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ):
        return _extract_docx(data)

    if any(lower_name.endswith(ext) for ext in _PLAIN_TEXT_EXTENSIONS) or content_type.startswith(
        "text/"
    ):
        return _extract_plain_text(data)

    return None


def chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """
    Quebra o texto em pedaços de tamanho ~chunk_size caracteres, com uma
    sobreposição entre eles (overlap) pra não cortar uma ideia bem no meio
    exatamente na fronteira entre dois pedaços.
    """
    if chunk_size <= 0 or not 0 <= overlap < chunk_size:
        raise ValueError("Tamanho de chunk e sobreposição inválidos")
    text = text.strip()
    if not text:
        return []

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end].strip())
        start = end - overlap

    return [c for c in chunks if c]

import asyncio
import base64
import logging
import re
import uuid
from io import BytesIO
from pathlib import Path

from fastapi import HTTPException
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.services.document_extraction import chunk_text, extract_text
from app.services.llm_provider import llm_provider

logger = logging.getLogger("buno.documents")


def _inspect_file(filename, content_type, data):
    is_image = content_type.startswith("image/") or Path(filename).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
    if is_image:
        if len(data) > 8 * 1024 * 1024:
            raise HTTPException(413, "Imagens devem ter no máximo 8 MB")
        try:
            with Image.open(BytesIO(data)) as image:
                if image.format not in {"PNG", "JPEG", "WEBP"}:
                    raise HTTPException(415, "Envie uma imagem PNG, JPEG ou WebP")
                if image.width * image.height > 20_000_000:
                    raise HTTPException(413, "A imagem excede 20 megapixels")
                mime = Image.MIME[image.format]
                image.verify()
            return mime, None
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(422, "Não foi possível ler essa imagem")
    try:
        text = extract_text(filename, content_type, data)
    except Exception:
        raise HTTPException(422, "O documento está danificado ou não pôde ser lido")
    if text is None:
        raise HTTPException(415, "Envie PDF, DOCX, texto, código ou uma imagem PNG/JPEG/WebP")
    if not text.strip():
        raise HTTPException(422, "Não encontramos texto neste documento. PDFs digitalizados precisam de OCR.")
    return content_type, text


async def save_and_process_document(db: AsyncSession, user_id, conversation_id, filename, content_type, data):
    filename = Path(filename.replace("\\", "/")).name[:255] or "arquivo"
    content_type, text = await run_in_threadpool(_inspect_file, filename, content_type, data)
    upload_dir = Path(settings.UPLOAD_DIR).resolve()
    upload_dir.mkdir(parents=True, exist_ok=True)
    storage_path = upload_dir / f"{uuid.uuid4().hex}.bin"
    note = None
    if text and len(text) > settings.DOCUMENT_MAX_TEXT_CHARS:
        note = f"Texto limitado aos primeiros {settings.DOCUMENT_MAX_TEXT_CHARS} caracteres."
        text = text[:settings.DOCUMENT_MAX_TEXT_CHARS]
    await run_in_threadpool(storage_path.write_bytes, data)
    if text:
        await run_in_threadpool(storage_path.with_suffix(".txt").write_text, text, "utf-8")
    document = Document(user_id=user_id, conversation_id=conversation_id, filename=filename,
        content_type=content_type, size_bytes=len(data), storage_path=str(storage_path),
        text_extracted=bool(text), processing_note=note)
    try:
        db.add(document)
        await db.commit()
        await db.refresh(document)
    except Exception:
        storage_path.unlink(missing_ok=True)
        storage_path.with_suffix(".txt").unlink(missing_ok=True)
        raise
    if not text:
        return document
    document_id = document.id
    pieces = chunk_text(text, settings.DOCUMENT_CHUNK_SIZE, settings.DOCUMENT_CHUNK_OVERLAP)[:settings.DOCUMENT_MAX_CHUNKS]
    # Plain text is already available. Indexing has a total deadline and fails open.
    try:
        async with asyncio.timeout(settings.DOCUMENT_PROCESS_TIMEOUT):
            for index, piece in enumerate(pieces):
                embedding = await llm_provider.embed(piece)
                db.add(DocumentChunk(document_id=document_id, chunk_index=index, content=piece, embedding=embedding))
            await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.warning("Indexação de documento indisponível (%s)", type(exc).__name__)
    return await db.get(Document, document_id)


def _text_fallback(documents, query):
    words = set(re.findall(r"\w{3,}", query.lower()))
    ranked = []
    for document in documents:
        sidecar = Path(document.storage_path).with_suffix(".txt")
        if not sidecar.is_file():
            continue
        text = sidecar.read_text(encoding="utf-8")[:settings.DOCUMENT_MAX_TEXT_CHARS]
        for index, part in enumerate(chunk_text(text, settings.DOCUMENT_CHUNK_SIZE, settings.DOCUMENT_CHUNK_OVERLAP)):
            score = sum(part.lower().count(word) for word in words)
            ranked.append((score, -index, f"[Trecho de {document.filename}]: {part}"))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [item[2] for item in ranked[:settings.RELEVANT_DOCUMENT_CHUNKS_LIMIT]]


async def retrieve_relevant_document_chunks(db: AsyncSession, conversation_id, query) -> list[str]:
    documents = (await db.execute(select(Document).where(Document.conversation_id == conversation_id))).scalars().all()
    if not documents:
        return []
    fallback = await run_in_threadpool(_text_fallback, documents, query)
    existing = (await db.execute(select(DocumentChunk.id).join(Document).where(Document.conversation_id == conversation_id).limit(1))).first()
    if not existing:
        return fallback
    try:
        async with asyncio.timeout(settings.CONTEXT_LOOKUP_TIMEOUT):
            embedding = await llm_provider.embed(query)
            distance = DocumentChunk.embedding.cosine_distance(embedding)
            result = await db.execute(select(DocumentChunk.content, Document.filename, distance.label("distance"))
                .join(Document, DocumentChunk.document_id == Document.id)
                .where(Document.conversation_id == conversation_id).order_by(distance)
                .limit(settings.RELEVANT_DOCUMENT_CHUNKS_LIMIT))
            rows = [f"[Trecho de {filename}]: {content}" for content, filename, dist in result.all() if dist is not None and dist <= 0.7]
            return rows or fallback
    except Exception as exc:
        await db.rollback()
        logger.warning("Busca vetorial indisponível (%s)", type(exc).__name__)
        return fallback


async def load_attached_images(db, user_id, conversation_id):
    rows = (await db.execute(select(Document).where(Document.conversation_id == conversation_id,
        Document.user_id == user_id, Document.content_type.in_(["image/png", "image/jpeg", "image/webp"]))
        .order_by(Document.created_at.desc()).limit(settings.MAX_IMAGES_PER_CHAT))).scalars().all()
    images = []
    for document in rows:
        path = Path(document.storage_path)
        if path.is_file() and path.stat().st_size <= 8 * 1024 * 1024:
            images.append(base64.b64encode(await run_in_threadpool(path.read_bytes)).decode("ascii"))
    return images

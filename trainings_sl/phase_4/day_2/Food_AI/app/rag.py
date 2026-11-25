import hashlib
import io
import os
import zipfile
from pathlib import Path

import chromadb
import pymupdf
from docx import Document as WordDocument
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Document, User
from .ai_provider import client, embedding_model, provider

MAX_UPLOAD = 5 * 1024 * 1024


def collection():
    path = os.getenv("CHROMA_PATH", "./data/chroma")
    name = "food_policies" if provider() == "openai" and embedding_model() == "text-embedding-3-small" else (
        "food_policies_" + hashlib.sha256(f"{provider()}:{embedding_model()}".encode()).hexdigest()[:16])
    return chromadb.PersistentClient(path=path).get_or_create_collection(name)


def extract(filename: str, raw: bytes):
    extension = Path(filename).suffix.lower()
    if extension == ".txt":
        try:
            return [(1, raw.decode("utf-8"))]
        except UnicodeDecodeError as exc:
            raise HTTPException(422, "TXT must be UTF-8") from exc
    if extension == ".pdf":
        try:
            with pymupdf.open(stream=raw, filetype="pdf") as doc:
                return [(i + 1, page.get_text()) for i, page in enumerate(doc)]
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(422, "Invalid PDF") from exc
    if extension == ".docx":
        try:
            doc = WordDocument(io.BytesIO(raw))
            return [(1, "\n".join(p.text for p in doc.paragraphs))]
        except (ValueError, KeyError, OSError, zipfile.BadZipFile) as exc:
            raise HTTPException(422, "Invalid DOCX") from exc
    raise HTTPException(422, "Only PDF, DOCX and TXT are supported")


def chunks(text: str):
    text = " ".join(text.split())
    for start in range(0, len(text), 600):
        part = text[start:start + 700]
        if part:
            yield part
        if start + 700 >= len(text):
            break


def index_document(db: Session, user: User, filename: str, raw: bytes):
    filename = Path(filename.replace("\\", "/")).name
    if not filename or len(filename) > 255 or not raw or len(raw) > MAX_UPLOAD:
        raise HTTPException(422, "Invalid filename or file size (maximum 5 MB)")
    pages = extract(filename, raw)
    parts = [(page, part) for page, text in pages for part in chunks(text)]
    if not parts or len(parts) > 1000:
        raise HTTPException(422, "Document is empty or has too many chunks")
    previous = db.scalars(select(Document).where(Document.filename == filename).with_for_update()).all()
    version = max((d.version for d in previous), default=0) + 1
    doc = Document(filename=filename, sha256=hashlib.sha256(raw).hexdigest(),
                   version=version, status="INDEXING", uploaded_by=user.id)
    db.add(doc)
    db.flush()
    ai = client()
    embeddings = []
    for start in range(0, len(parts), 100):
        batch = parts[start:start + 100]
        vectors = ai.embeddings.create(model=embedding_model(), input=[part for _, part in batch])
        if len(vectors.data) != len(batch):
            raise HTTPException(503, "Embedding provider returned an incomplete response")
        embeddings.extend(entry.embedding for entry in sorted(vectors.data, key=lambda entry: entry.index))
    ids = [f"{doc.id}:{i}" for i in range(len(parts))]
    collection().add(ids=ids, embeddings=embeddings,
                     documents=[part for _, part in parts],
                     metadatas=[{"document_id": doc.id, "filename": filename, "page": page, "version": version}
                                for page, _ in parts])
    for old in previous:
        old.status = "INACTIVE"
    doc.status = "ACTIVE"
    return doc


def retrieve(db: Session, question: str):
    ids = list(db.scalars(select(Document.id).where(Document.status == "ACTIVE")).all())
    if not ids:
        return []
    vector = client().embeddings.create(model=embedding_model(),
                                        input=[question]).data[0].embedding
    result = collection().query(query_embeddings=[vector], n_results=4,
                                where={"document_id": {"$in": ids}}, include=["documents", "metadatas", "distances"])
    return [{"text": text, "source": meta["filename"], "page": meta["page"], "version": meta["version"],
             "chunk_id": chunk_id}
            for chunk_id, text, meta, distance in zip(result["ids"][0], result["documents"][0],
                                                       result["metadatas"][0], result["distances"][0])
            if distance <= 1.0]

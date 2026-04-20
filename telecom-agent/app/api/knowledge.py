"""
Router para gestión de la base de conocimiento (RAG).

Endpoints:
  GET    /knowledge                       — listar archivos
  GET    /knowledge/{filename}            — leer contenido
  PUT    /knowledge/{filename}            — actualizar contenido
  POST   /knowledge                       — subir archivo nuevo
  DELETE /knowledge/{filename}            — borrar archivo
  POST   /knowledge/reindex               — disparar re-indexado (background)
  GET    /knowledge/reindex/{job_id}      — consultar estado del job
"""
import asyncio
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.rag.indexer import index_knowledge_base

logger = logging.getLogger(__name__)

router = APIRouter()

KNOWLEDGE_DIR = (Path(__file__).parent.parent.parent / "knowledge").resolve()
ALLOWED_EXTENSIONS = {".md", ".txt", ".pdf", ".docx", ".pptx"}
DOCLING_EXTENSIONS = {".pdf", ".docx", ".pptx"}
DOCLING_URL = "http://docling:5001/v1/convert/file"

# ---------------------------------------------------------------------------
# In-memory job registry (suficiente para una herramienta de desarrollo)
# ---------------------------------------------------------------------------

_jobs: dict[str, dict] = {}
_reindex_lock = asyncio.Lock()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class KnowledgeFileInfo(BaseModel):
    name: str
    size_bytes: int
    modified_iso: str


class KnowledgeFileContent(BaseModel):
    name: str
    content: str


class KnowledgeFileUpdate(BaseModel):
    content: str


class ReindexJobResponse(BaseModel):
    job_id: str
    status: str


class ReindexJobStatus(BaseModel):
    job_id: str
    status: str
    chunks_indexed: Optional[int] = None
    error_detail: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_path(filename: str) -> Path:
    """Valida que el filename no escape del KNOWLEDGE_DIR (path traversal)."""
    if "/" in filename or "\\" in filename or filename.startswith("."):
        raise HTTPException(status_code=400, detail="Nombre de archivo inválido.")
    resolved = (KNOWLEDGE_DIR / filename).resolve()
    if not str(resolved).startswith(str(KNOWLEDGE_DIR)):
        raise HTTPException(status_code=400, detail="Acceso denegado.")
    return resolved


def _file_info(path: Path) -> KnowledgeFileInfo:
    stat = path.stat()
    return KnowledgeFileInfo(
        name=path.name,
        size_bytes=stat.st_size,
        modified_iso=datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
    )


async def _extract_with_docling(file_bytes: bytes, filename: str) -> str:
    """Envía el archivo a Docling y devuelve el texto extraído como markdown."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            DOCLING_URL,
            files={"files": (filename, file_bytes, "application/octet-stream")},
        )
    resp.raise_for_status()
    data = resp.json()
    doc = data.get("document", {})
    md_text = doc.get("md_content") or doc.get("export_formats", {}).get("md", "")
    if not md_text:
        raise ValueError(f"Docling no devolvió contenido markdown para {filename}")
    return md_text


def _run_reindex(job_id: str) -> None:
    """Función sincrónica ejecutada en un thread. Actualiza el estado del job."""
    _jobs[job_id]["status"] = "running"
    try:
        chunks = index_knowledge_base(force=True)
        _jobs[job_id]["status"] = "done"
        _jobs[job_id]["chunks_indexed"] = chunks
    except Exception as exc:
        logger.error("Re-indexado falló: %s", exc)
        _jobs[job_id]["status"] = "error"
        _jobs[job_id]["error_detail"] = str(exc)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=list[KnowledgeFileInfo])
async def list_knowledge_files():
    """Lista todos los archivos .md y .txt en knowledge/."""
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(
        [p for p in KNOWLEDGE_DIR.iterdir() if p.is_file() and p.suffix in ALLOWED_EXTENSIONS],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return [_file_info(f) for f in files]


@router.get("/reindex/{job_id}", response_model=ReindexJobStatus)
async def get_reindex_status(job_id: str):
    """Consulta el estado de un job de re-indexado."""
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Job no encontrado.")
    job = _jobs[job_id]
    return ReindexJobStatus(
        job_id=job_id,
        status=job["status"],
        chunks_indexed=job.get("chunks_indexed"),
        error_detail=job.get("error_detail"),
    )


@router.get("/{filename}", response_model=KnowledgeFileContent)
async def get_knowledge_file(filename: str):
    """Devuelve el contenido de un archivo."""
    path = _safe_path(filename)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Archivo '{filename}' no encontrado.")
    return KnowledgeFileContent(name=filename, content=path.read_text(encoding="utf-8"))


@router.put("/{filename}", response_model=KnowledgeFileInfo)
async def update_knowledge_file(filename: str, body: KnowledgeFileUpdate):
    """Reemplaza el contenido de un archivo existente."""
    path = _safe_path(filename)
    if path.suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=422, detail="Solo se permiten archivos .md o .txt.")
    path.write_text(body.content, encoding="utf-8")
    return _file_info(path)


@router.post("", response_model=KnowledgeFileInfo, status_code=201)
async def upload_knowledge_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
):
    """
    Sube un archivo nuevo a knowledge/.
    Acepta .md y .txt (guardado directo) o .pdf/.docx/.pptx (extraídos via Docling → guardados como .md).
    Dispara un re-indexado automático tras el upload.
    """
    if not file.filename:
        raise HTTPException(status_code=422, detail="Nombre de archivo requerido.")
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=422,
            detail=f"Tipo no soportado. Permitidos: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    file_bytes = await file.read()

    if suffix in DOCLING_EXTENSIONS:
        try:
            md_text = await _extract_with_docling(file_bytes, file.filename)
        except httpx.HTTPStatusError as exc:
            raise HTTPException(status_code=502, detail=f"Docling devolvió error {exc.response.status_code}.")
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Error al procesar con Docling: {exc}")

        save_name = Path(file.filename).stem + ".md"
        path = _safe_path(save_name)
        path.write_text(md_text, encoding="utf-8")
    else:
        path = _safe_path(Path(file.filename).name)
        path.write_bytes(file_bytes)

    # Re-indexado automático en background
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"status": "pending", "chunks_indexed": None, "error_detail": None}
    background_tasks.add_task(asyncio.to_thread, _run_reindex, job_id)

    return _file_info(path)


@router.delete("/{filename}")
async def delete_knowledge_file(filename: str):
    """Elimina un archivo."""
    path = _safe_path(filename)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Archivo '{filename}' no encontrado.")
    path.unlink()
    return {"deleted": True, "name": filename}


@router.post("/reindex", response_model=ReindexJobResponse, status_code=202)
async def trigger_reindex(background_tasks: BackgroundTasks):
    """
    Dispara el re-indexado de la base de conocimiento en un thread separado.
    Devuelve un job_id para consultar el progreso.
    """
    # Verificar si ya hay un job corriendo
    running = [j for j in _jobs.values() if j["status"] in ("pending", "running")]
    if running:
        raise HTTPException(
            status_code=409,
            detail="Ya hay un re-indexado en curso. Esperá a que termine.",
        )

    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"status": "pending", "chunks_indexed": None, "error_detail": None}

    background_tasks.add_task(asyncio.to_thread, _run_reindex, job_id)
    return ReindexJobResponse(job_id=job_id, status="pending")

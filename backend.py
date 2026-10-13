from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAI
from pydantic import BaseModel, Field

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

from pdf_processor import (
    EXTRACTED_DIR,
    NOT_EXTRACTED_DIR,
    DEFAULT_VECTOR_STORE_NAME,
    MAX_FILES_PER_BATCH,
    ensure_vector_store,
    process_pdfs,
)
from state_utils import VectorStoreState

APP_TITLE = "AreaBot2 Assistant"
STATE_FILE = Path("vector_store_state.json")
CONVERSATION_DIR = Path("conversation_memory")
MAX_TURNS = 10
STATIC_DIR = Path("frontend")
SYSTEM_PROMPT = (
    "Eres AreaBot2, el especialista en HVAC que representa a Area Cooling Solutions. "
    "Habla con la certeza de un técnico experimentado y ofrece respuestas claras, concisas y directamente accionables. "
    "Utiliza únicamente la información disponible en la base de conocimiento. Si los datos no están presentes o son insuficientes, dilo explícitamente y describe qué información sí tienes. "
    "Puedes realizar suposiciones prácticas razonables (manejo, instalación o uso típico), pero nunca inventes especificaciones técnicas. No cites documentos ni fuentes: presenta los hechos como conocimiento propio. "
    "Mantén un tono profesional y cercano; formula preguntas breves de seguimiento cuando ayuden a comprender mejor la necesidad del usuario. "
    "Para cualquier consulta sobre gases refrigerantes, remite la respuesta a la ley de la UE 2024/573 y menciónalo explícitamente. "
    "Si trabajas con datos tabulares, revisa dos veces que cada columna conserve su significado y que los campos vacíos no desplacen la información. Cuando encuentres celdas en blanco, determina con el contexto si indican un cero, un valor desconocido u otra condición; explica tu criterio o señala la ambigüedad antes de responder. "
    "Cuando te soliciten datos de potencia, proporciona siempre la potencia nominal máxima como límite superior; evita promedios o mínimos. "
    "Si recomiendas un equipo según un requisito de potencia, elige el modelo cuya potencia máxima sea la menor que aún cumpla o supere el valor solicitado; nunca propongas un equipo cuya potencia máxima quede por debajo del requisito."
)

logger = logging.getLogger(__name__)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    session_id: str
    answer: str


class ConversationStore:
    """Persist bounded chat transcripts per session so conversations survive reloads."""
    def __init__(self, base_dir: Path, max_turns: int) -> None:
        self.base_dir = base_dir
        self.max_turns = max_turns
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str) -> Path:
        return self.base_dir / f"{session_id}.jsonl"

    def load_turns(self, session_id: str) -> List[Dict[str, str]]:
        path = self._path(session_id)
        if not path.exists():
            return []
        turns: List[Dict[str, str]] = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    turns.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.warning("Skipping malformed memory line for %s", session_id)
        return turns[-self.max_turns :]

    def save_turns(self, session_id: str, turns: List[Dict[str, str]]) -> None:
        bounded = turns[-self.max_turns :]
        path = self._path(session_id)
        with path.open("w", encoding="utf-8") as handle:
            for turn in bounded:
                handle.write(json.dumps(turn, ensure_ascii=True) + "\n")


app = FastAPI(title=APP_TITLE)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def build_message_history(turns: List[Dict[str, str]]) -> List[Dict[str, str]]:
    history: List[Dict[str, str]] = []
    for turn in turns[-MAX_TURNS:]:
        user_text = turn.get("user")
        assistant_text = turn.get("assistant")
        if user_text:
            history.append({"role": "user", "content": user_text})
        if assistant_text:
            history.append({"role": "assistant", "content": assistant_text})
    return history


def describe_file(path: Path, *, extracted: bool, state: VectorStoreState) -> Dict[str, object]:
    stats = path.stat()
    entry = state.get_entry(path.name) if extracted else None
    return {
        "name": path.name,
        "size": stats.st_size,
        "modified": stats.st_mtime,
        "vector_file_id": entry.get("vector_file_id") if entry else None,
        "source_file_id": entry.get("source_file_id") if entry else None,
        "url": f"/pdfs/{path.name}" if extracted else None,
    }


def list_directory(directory: Path) -> List[Path]:
    if not directory.exists():
        return []
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() == ".pdf"
    )


def sanitize_filename(raw_name: str) -> str:
    name = Path(raw_name).name
    allowed = {"-", "_", ".", " ", "(", ")"}
    cleaned = "".join(ch if ch.isalnum() or ch in allowed else "_" for ch in name)
    if not cleaned.lower().endswith(".pdf"):
        cleaned = f"{cleaned}.pdf"
    return cleaned


@app.on_event("startup")
def startup() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if load_dotenv:
        load_dotenv()

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY environment variable must be set")

    app.state.client = OpenAI(api_key=api_key)
    app.state.state = VectorStoreState(STATE_FILE)
    app.state.conversations = ConversationStore(CONVERSATION_DIR, MAX_TURNS)

    for directory in (NOT_EXTRACTED_DIR, EXTRACTED_DIR, STATIC_DIR):
        directory.mkdir(parents=True, exist_ok=True)

    app.state.vector_store_id = ensure_vector_store(
        app.state.client,
        name=DEFAULT_VECTOR_STORE_NAME,
        state=app.state.state,
    )

    existing_paths = {route.path for route in app.routes}
    if "/static" not in existing_paths:
        app.mount("/static", StaticFiles(directory=STATIC_DIR, html=False), name="static")
    if "/pdfs" not in existing_paths:
        app.mount("/pdfs", StaticFiles(directory=EXTRACTED_DIR, html=False), name="pdfs")


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=500, detail="Interfaz no encontrada")
    return index_path.read_text(encoding="utf-8")


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    session_id = request.session_id or uuid4().hex
    turns = app.state.conversations.load_turns(session_id)

    turns.append({"user": request.message})
    history = build_message_history(turns)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, *history]

    client: OpenAI = app.state.client
    vector_store_id: str = app.state.vector_store_id

    try:
        response = client.responses.create(
            model="gpt-5",
            reasoning={"effort": "low"},
            input=messages,
            tools=[{"type": "file_search", "vector_store_ids": [vector_store_id]}],
        )
    except Exception as exc:  # broad catch to surface API issues cleanly
        logger.exception("Chat completion failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    answer = response.output_text
    turns[-1]["assistant"] = answer
    app.state.conversations.save_turns(session_id, turns)
    return ChatResponse(session_id=session_id, answer=answer)


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    session_id = request.session_id or uuid4().hex
    turns = app.state.conversations.load_turns(session_id)

    turns.append({"user": request.message})
    history = build_message_history(turns)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, *history]

    client: OpenAI = app.state.client
    vector_store_id: str = app.state.vector_store_id

    def stream_response():
        yield json.dumps({"type": "session", "session_id": session_id}) + "\n"
        answer_parts: List[str] = []
        try:
            with client.responses.stream(
                model="gpt-5",
                reasoning={"effort": "low"},
                input=messages,
                tools=[{"type": "file_search", "vector_store_ids": [vector_store_id]}],
            ) as stream:
                for event in stream:
                    if event.type == "response.output_text.delta":
                        delta = event.delta or ""
                        if delta:
                            answer_parts.append(delta)
                            yield json.dumps({"type": "delta", "text": delta}) + "\n"
                    elif event.type == "response.error":
                        error_msg = str(getattr(event, "error", "Unknown error"))
                        raise RuntimeError(error_msg)
                stream.get_final_response()
        except Exception as exc:
            logger.exception("Chat streaming failed")
            turns.pop()
            yield json.dumps({"type": "error", "error": str(exc)}) + "\n"
            return

        answer = "".join(answer_parts)
        if answer:
            turns[-1]["assistant"] = answer
            app.state.conversations.save_turns(session_id, turns)
        else:
            turns.pop()

        yield json.dumps({"type": "done"}) + "\n"

    return StreamingResponse(stream_response(), media_type="text/plain")


@app.get("/api/pdfs")
async def list_pdfs_endpoint() -> Dict[str, List[Dict[str, object]]]:
    pending = [describe_file(path, extracted=False, state=app.state.state) for path in list_directory(NOT_EXTRACTED_DIR)]
    processed = [describe_file(path, extracted=True, state=app.state.state) for path in list_directory(EXTRACTED_DIR)]
    return {"pending": pending, "processed": processed}


@app.post("/api/pdfs/upload")
async def upload_pdfs(files: List[UploadFile] = File(...)) -> Dict[str, List[str]]:
    if not files:
        raise HTTPException(status_code=400, detail="No se proporcionaron archivos")

    saved: List[str] = []
    for file in files:
        if not file.filename:
            continue
        if not file.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail=f"{file.filename} no es un PDF")
        filename = sanitize_filename(file.filename)
        destination = NOT_EXTRACTED_DIR / filename
        with destination.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        file.file.close()
        saved.append(filename)

    return {"queued": saved}


@app.post("/api/pdfs/process")
async def process_pdfs_endpoint() -> Dict[str, List[str]]:
    processed_paths = process_pdfs(
        source_dir=NOT_EXTRACTED_DIR,
        destination_dir=EXTRACTED_DIR,
        vector_store_id=app.state.vector_store_id,
        client=app.state.client,
        state=app.state.state,
    )
    return {"processed": [path.name for path in processed_paths]}


@app.delete("/api/pdfs/{filename}")
async def delete_pdf(filename: str) -> Dict[str, str]:
    decoded = Path(filename).name
    path = EXTRACTED_DIR / decoded
    if not path.exists():
        raise HTTPException(status_code=404, detail="PDF no encontrado")

    entry = app.state.state.get_entry(decoded)
    vector_file_id = entry.get("vector_file_id") if entry else None
    source_file_id = entry.get("source_file_id") if entry else None

    client: OpenAI = app.state.client
    vector_store_id: str = app.state.vector_store_id

    if not vector_file_id or not source_file_id:
        # Fallback: query the vector store to reconcile stray files that predate state tracking.
        try:
            remote_files = client.vector_stores.files.list(vector_store_id=vector_store_id)
        except Exception as exc:
            logger.warning("Failed to list vector store files during reconciliation: %s", exc)
            remote_files = None

        if remote_files:
            for remote in getattr(remote_files, "data", []):
                candidate_source = getattr(remote, "file_id", None)
                if not candidate_source:
                    continue
                try:
                    source_meta = client.files.retrieve(file_id=candidate_source)
                except Exception:  # retrieval is best-effort
                    continue
                if getattr(source_meta, "filename", None) == decoded:
                    vector_file_id = getattr(remote, "id", None)
                    source_file_id = candidate_source
                    if vector_file_id:
                        app.state.state.record_file(
                            decoded,
                            vector_file_id,
                            source_file_id=source_file_id,
                            uploaded_at=getattr(remote, "created_at", None),
                        )
                    break

    if vector_file_id:
        try:
            client.vector_stores.files.delete(
                vector_store_id=vector_store_id,
                file_id=vector_file_id,
            )
        except Exception as exc:
            logger.exception("Failed to remove %s from vector store", decoded)
            raise HTTPException(status_code=502, detail=f"Error al eliminar en el vector store: {exc}") from exc

    if source_file_id:
        try:
            client.files.delete(file_id=source_file_id)
        except Exception:
            logger.info("Source file %s already removed", source_file_id)

    path.unlink()
    app.state.state.remove_file(decoded)
    return {"status": "deleted"}


@app.get("/pdfs/{filename}")
async def get_pdf(filename: str) -> FileResponse:
    decoded = Path(filename).name
    path = EXTRACTED_DIR / decoded
    if not path.exists():
        raise HTTPException(status_code=404, detail="PDF no encontrado")
    return FileResponse(path, media_type="application/pdf", filename=decoded)


@app.get("/api/config")
async def get_config() -> Dict[str, object]:
    return {
        "vector_store_id": app.state.vector_store_id,
        "max_files_per_batch": MAX_FILES_PER_BATCH,
        "title": APP_TITLE,
    }
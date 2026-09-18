"""
SilentGPT Backend — main.py
FastAPI application — entry point.

Architecture: Fully Stateless / Zero Data Retention
  - No database
  - No session storage
  - No message logging
  - All request data lives only in the request's async coroutine scope
    and is garbage-collected when the response is sent.

Run:
    uvicorn main:app --reload --host 0.0.0.0 --port 8000
"""

import gc
import logging
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from config import Settings, get_settings
from models import (
    ChatRequest, ChatResponse,
    ImageResponse,
    HealthResponse, ErrorResponse,
    SearchSource,
)
from search import search_web, format_sources_for_prompt
from ai import generate_response, analyse_image, is_ollama_healthy
from image_handler import (
    validate_image, extract_metadata, build_fallback_description,
    ImageTooLargeError, UnsupportedImageTypeError,
)


# ── Logging ───────────────────────────────────────────────────────────────────
# ZDR: We log INFO-level server events (startup, errors) but NEVER log
#      user message content, uploaded images, or search queries.

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("silentgpt")


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown hooks."""
    cfg = get_settings()
    logger.info("SilentGPT backend starting — Zero Data Retention mode: %s", cfg.ZERO_DATA_RETENTION)
    logger.info("Ollama URL: %s | Model: %s", cfg.OLLAMA_BASE_URL, cfg.OLLAMA_MODEL)
    yield
    logger.info("SilentGPT backend shutting down.")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="SilentGPT API",
    description=(
        "Privacy-first AI chatbot backend. "
        "Zero Data Retention — no messages, images, or queries are stored."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",    # Swagger UI — disable in production if desired
    redoc_url="/redoc",
)


# ── CORS ──────────────────────────────────────────────────────────────────────

settings = get_settings()

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,   # set to your frontend URL in .env
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ── Helper ────────────────────────────────────────────────────────────────────

def _build_chat_prompt(user_message: str, search_context: str) -> str:
    """
    Assembles the prompt sent to Ollama.
    If live search results exist, injects them into the prompt.
    Otherwise passes the user question directly to Ollama.
    Built fresh in memory for every request — never logged or saved.
    """
    if search_context and search_context.strip():
        return (
            f"{search_context.strip()}\n\n"
            f"[User Question]\n{user_message}\n\n"
            "[Instructions]\n"
            "Using the web search results above, answer the user's question accurately "
            "and concisely. Cite sources where relevant."
        )
    return user_message


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    tags=["System"],
)
async def health_check(cfg: Settings = Depends(get_settings)):
    """
    Returns server status and dependency connectivity.
    Safe to expose publicly — returns no user data.
    """
    ollama_ok = await is_ollama_healthy()
    search_ok = bool(cfg.TAVILY_API_KEY or cfg.SERPER_API_KEY)

    return HealthResponse(
        status="ok",
        ollama_connected=ollama_ok,
        search_configured=search_ok,
        zero_data_retention=True,
    )


@app.post(
    "/chat",
    response_model=ChatResponse,
    summary="Send a message to SilentGPT",
    tags=["Chat"],
    responses={
        500: {"model": ErrorResponse, "description": "AI or search error"},
        503: {"model": ErrorResponse, "description": "Ollama not available"},
    },
)
async def chat(
    request: ChatRequest,
    cfg: Settings = Depends(get_settings),
):
    """
    Main chat endpoint.

    Flow:
      1. Receive user message (validated by Pydantic, never logged)
      2. Search the web for relevant information
      3. Build a prompt combining search results + user question
      4. Send prompt to Ollama (Phi-3 Mini by default)
      5. Return AI response + source URLs
      6. All local variables are discarded (ZDR)

    ⚠️  ZDR Guarantee: no data from this request is written to any
        persistent storage (disk, DB, log file, cache).
    """
    sources: list[SearchSource] = []
    prompt: str = ""
    response_text: str = ""

    try:
        # Step 1 — Web search
        # ZDR: query is a local variable; not logged or stored.
        sources = await search_web(request.message)
        search_context = format_sources_for_prompt(sources)

        # Step 2 — Build prompt (in-memory only)
        prompt = _build_chat_prompt(request.message, search_context)

        # Step 3 — Generate response via Ollama
        response_text = await generate_response(prompt, model=cfg.OLLAMA_MODEL)

        if not response_text:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Ollama returned an empty response. Is the model loaded?",
            )

    except HTTPException:
        raise

    except Exception as exc:
        # Catch-all for search/network failures — surface a clean error
        logger.error("Chat endpoint error: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while processing your request.",
        )

    finally:
        # ── ZDR Cleanup ──────────────────────────────────────────
        # Explicitly delete large in-memory objects.
        # Python's GC would collect these anyway, but we do it
        # explicitly to make the ZDR guarantee crystal-clear.
        del prompt
        gc.collect()

    return ChatResponse(
        response=response_text,
        sources=sources,
        private=True,
        model=cfg.OLLAMA_MODEL,
    )


@app.post(
    "/image",
    response_model=ImageResponse,
    summary="Upload and analyse an image",
    tags=["Image"],
    responses={
        400: {"model": ErrorResponse, "description": "Invalid image"},
        413: {"model": ErrorResponse, "description": "Image too large"},
        500: {"model": ErrorResponse, "description": "Processing error"},
    },
)
async def analyse_image_endpoint(
    file: UploadFile = File(..., description="Image file to analyse"),
    instruction: str = Form(
        default="Describe this image in detail.",
        max_length=500,
        description="What you want the AI to do with the image.",
    ),
    cfg: Settings = Depends(get_settings),
):
    """
    Image analysis endpoint.

    Flow:
      1. Receive uploaded file into memory (never written to disk)
      2. Validate file type and size
      3. Send image bytes to Ollama vision model (or fallback to metadata)
      4. Return AI analysis
      5. Explicitly delete bytes from memory (ZDR)

    ⚠️  ZDR Guarantee: the image is processed entirely in RAM.
        It is never saved to disk, a database, or any external service
        other than the local Ollama instance.
    """
    image_bytes: bytes | None = None
    analysis: str = ""

    try:
        # Step 1 — Read file into memory
        content_type = file.content_type or "application/octet-stream"
        image_bytes = await file.read()

        # Step 2 — Validate (raises on failure)
        try:
            validate_image(image_bytes, content_type)
        except ImageTooLargeError as e:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(e))
        except UnsupportedImageTypeError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

        # Step 3 — Try vision LLM first; fall back to metadata description
        try:
            analysis = await analyse_image(
                image_bytes=image_bytes,
                instruction=instruction,
                model=cfg.OLLAMA_VISION_MODEL,
            )
        except Exception:
            logger.warning(
                "Vision model '%s' unavailable — using metadata fallback.",
                cfg.OLLAMA_VISION_MODEL,
            )
            metadata = extract_metadata(image_bytes)
            analysis = build_fallback_description(metadata)

    except HTTPException:
        raise

    except Exception:
        logger.error("Image endpoint unexpected error.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while processing the image.",
        )

    finally:
        # ── ZDR Cleanup ──────────────────────────────────────────
        if image_bytes is not None:
            del image_bytes   # drop the bytes from RAM
        gc.collect()

    return ImageResponse(analysis=analysis, private=True)


# ── Global exception handler ─────────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """
    Catch-all handler. Returns a generic error without leaking
    internal details or user data.
    """
    logger.error("Unhandled exception: %s", type(exc).__name__)
    return JSONResponse(
        status_code=500,
        content={"detail": "An unexpected error occurred.", "private": True},
    )


# ── Serve Static Frontend Files (if present) ──────────────────────────────────
FRONTEND_DIR = Path(__file__).resolve().parent.parent
if (FRONTEND_DIR / "index.html").exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


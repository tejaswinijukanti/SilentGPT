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

import os
import gc
import base64
import logging
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, FileResponse
from fastapi.staticfiles import StaticFiles

from config import Settings, get_settings
from gemini_edit import gemini_process_image, gemini_edit_image, is_advanced_edit, gemini_generate_image
from models import (
    ChatRequest, ChatResponse,
    ImageResponse,
    HealthResponse, ErrorResponse,
    SearchSource,
)
from search import search_web
from ai import (
    generate_response,
    generate_response_with_model,
    analyse_image,
    is_ollama_healthy,
    is_groq_healthy,
    is_gemini_healthy,
)
from image_handler import (
    validate_image, extract_metadata, build_fallback_description,
    process_image, detect_edit_action, SUPPORTED_ACTIONS,
    ImageTooLargeError, UnsupportedImageTypeError,
)
from document_generator import create_document, create_presentation
from content_generator import generate_document_content, generate_presentation_content



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
    has_groq = bool(os.getenv("GROQ_API_KEY", "").strip() or cfg.GROQ_API_KEY.strip())
    has_gemini = bool(os.getenv("GEMINI_API_KEY", "").strip() or cfg.GEMINI_API_KEY.strip())
    logger.info("SilentGPT backend starting — Zero Data Retention mode: %s", cfg.ZERO_DATA_RETENTION)
    logger.info(
        "Hybrid Architecture: Text/Docs -> Groq (%s) [Gemini failover], Images -> Gemini (%s)",
        cfg.GROQ_MODEL if has_groq else "(groq unconfigured)",
        cfg.GEMINI_MODEL if has_gemini else "(gemini unconfigured)",
    )
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
if settings.GEMINI_API_KEY and not os.getenv("GEMINI_API_KEY"):
    os.environ["GEMINI_API_KEY"] = settings.GEMINI_API_KEY
if settings.GROQ_API_KEY and not os.getenv("GROQ_API_KEY"):
    os.environ["GROQ_API_KEY"] = settings.GROQ_API_KEY

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,   # set to your frontend URL in .env
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ── Helper ────────────────────────────────────────────────────────────────────

def _build_chat_prompt(user_message: str, sources: list) -> str:
    """
    Assembles the prompt sent to Ollama.
    Injects numbered web-search results as context when available.
    Built fresh in memory for every request — never logged or saved.
    """
    if sources:
        context = ""
        for i, source in enumerate(sources, start=1):
            context += f"Source {i}:\nTitle: {source.title}\nContent: {source.snippet}\n\n"
    else:
        context = "No relevant information found from the internet."

    return f"""You are SilentGPT, a helpful and private AI assistant.
Use the following information collected from the internet to answer the user's question.
If the information is insufficient, politely say that you couldn't find enough information.
Do NOT mention that you are using search results — just answer naturally.
Never store, repeat, or log the user's message.

Internet Information:
{context}
User Question: {user_message}

Answer clearly and concisely:"""


def needs_web_search(message: str) -> bool:
    """
    Return True only when the message needs live internet search.
    Casual conversation → False (fast local reply).
    """
    text = message.lower().strip()

    # Casual phrases — do NOT search
    casual = [
        "hi", "hello", "hey", "good morning", "good evening", "good night",
        "how are you", "what's up", "whats up", "thank you", "thanks",
        "ok", "okay", "bye", "see you", "who are you", "what can you do",
        "help", "what is your name", "yo", "sup"
    ]

    for phrase in casual:
        if text == phrase or text.startswith(phrase + " ") or text.endswith(" " + phrase):
            return False

    # Very short messages without numbers → usually casual
    if len(text.split()) <= 2 and not any(c.isdigit() for c in text):
        return False

    # Keywords that usually need live data
    search_keywords = [
        "current", "latest", "today", "now", "price", "news", "weather",
        "stock", "who won", "score", "update", "recent", "live",
        "bitcoin", "crypto", "gold rate", "dollar rate", "election",
        "what happened", "breaking"
    ]
    if any(k in text for k in search_keywords):
        return True

    # Factual questions
    question_starters = ["what", "who", "when", "where", "which", "how much", "how many"]
    if any(text.startswith(q) for q in question_starters):
        return True

    return False


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
    groq_ok = bool(os.getenv("GROQ_API_KEY", "").strip() or cfg.GROQ_API_KEY.strip())
    gemini_ok = bool(os.getenv("GEMINI_API_KEY", "").strip() or cfg.GEMINI_API_KEY.strip())
    ollama_ok = (await is_ollama_healthy()) if not (groq_ok or gemini_ok) else False
    search_ok = bool(cfg.TAVILY_API_KEY or cfg.SERPER_API_KEY)

    primary = "groq" if groq_ok else ("gemini" if gemini_ok else "ollama")

    return HealthResponse(
        status="ok",
        ollama_connected=groq_ok or gemini_ok or ollama_ok,
        search_configured=search_ok,
        zero_data_retention=True,
        groq_configured=groq_ok,
        gemini_configured=gemini_ok,
        primary_provider=primary,
    )


@app.post(
    "/chat",
    response_model=ChatResponse,
    summary="Send a message to SilentGPT",
    tags=["Chat"],
    responses={
        500: {"model": ErrorResponse, "description": "AI or search error"},
        503: {"model": ErrorResponse, "description": "AI provider not available"},
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
      4. Send prompt to primary AI provider (Groq API with Gemini failover)
      5. Return AI response + source URLs
      6. All local variables are discarded (ZDR)

    ⚠️  ZDR Guarantee: no data from this request is written to any
        persistent storage (disk, DB, log file, cache).
    """
    sources: list[SearchSource] = []
    prompt: str = ""
    response_text: str = ""
    active_model: str = ""

    try:
        # Smart decision: search only when needed
        if needs_web_search(request.message):
            sources = await search_web(request.message)
            prompt = _build_chat_prompt(request.message, sources)
        else:
            # Normal conversation — no internet search
            prompt = request.message

        response_text, active_model = await generate_response_with_model(prompt)

        if not response_text:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="AI provider returned an empty response.",
            )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Chat endpoint error: %s: %s", type(exc).__name__, exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "detail": f"An error occurred while processing your request: {exc}",
                "error": str(exc),
                "private": True,
            },
        )
    finally:
        del prompt
        gc.collect()

    return ChatResponse(
        response=response_text,
        sources=sources,
        private=True,
        model=active_model,
    )


@app.post("/image")
async def image_endpoint(
    file: UploadFile = File(...),
    instruction: str = Form(""),
    message: str = Form(""),
):
    image_bytes = await file.read()
    text = (instruction or message or "Describe this image.").strip()
    try:
        return await gemini_process_image(text, image_bytes=image_bytes)
    except Exception as e:
        return {"type": "text", "response": f"Image request failed: {e}"}
    finally:
        del image_bytes
        gc.collect()


@app.post("/generate-image")
async def generate_image_endpoint(request: dict, cfg: Settings = Depends(get_settings)):
    prompt = (request.get("prompt") or request.get("message") or "").strip()
    if not prompt:
        return JSONResponse(
            status_code=400,
            content={
                "error": "Describe the image you want.",
                "detail": "Describe the image you want.",
                "type": "text",
                "response": "Describe the image you want.",
                "private": True,
            },
        )

    gemini_key = os.getenv("GEMINI_API_KEY", "").strip() or cfg.GEMINI_API_KEY.strip()
    if not gemini_key:
        return JSONResponse(
            status_code=500,
            content={
                "error": "Image generation requires GEMINI_API_KEY to be configured.",
                "detail": "Image generation requires GEMINI_API_KEY to be configured.",
                "type": "text",
                "response": "Image generation requires GEMINI_API_KEY to be configured.",
                "private": True,
            },
        )

    try:
        img_bytes = gemini_generate_image(prompt)
        b64 = base64.b64encode(img_bytes).decode("utf-8")
        return {
            "image": f"data:image/png;base64,{b64}",
            "action": "generate",
            "type": "image",
            "response": "Done.",
            "private": True,
        }
    except Exception as e:
        logger.error("Gemini generate failed: %s", e)
        return JSONResponse(
            status_code=500,
            content={
                "error": f"Image generation failed: {e}",
                "detail": f"Image generation failed: {e}",
                "type": "text",
                "response": f"Image generation failed: {e}",
                "private": True,
            },
        )



@app.post(
    "/image/process",
    summary=(
        "Perform image editing — actions: "
        + ", ".join(sorted(SUPPORTED_ACTIONS))
    ),
    tags=["Image"],
    responses={
        200: {"content": {"image/png": {}}, "description": "Processed image binary"},
        400: {"model": ErrorResponse, "description": "Invalid image or action"},
        500: {"model": ErrorResponse, "description": "Processing error"},
    },
)
async def process_image_endpoint(
    file: UploadFile = File(..., description="Image file to process"),
    action: str = Form(
        default="remove_bg",
        description=(
            "Editing action. One of: " + ", ".join(sorted(SUPPORTED_ACTIONS))
        ),
    ),
    level: float | None = Form(
        default=None,
        description=(
            "Optional intensity / magnitude for the chosen action "
            "(e.g. blur radius, rotation degrees, brightness multiplier). "
            "Falls back to a sensible default when omitted."
        ),
    ),
):
    """
    Perform image editing in-memory.
    Supported actions: remove_bg, grayscale, blur, sharpen, brightness,
    contrast, saturation, rotate, flip_h, flip_v, crop.
    Zero Data Retention: image is never saved to disk; memory is purged after response.
    """
    if action not in SUPPORTED_ACTIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Invalid action '{action}'. "
                f"Valid actions: {', '.join(sorted(SUPPORTED_ACTIONS))}"
            ),
        )

    content_type = file.content_type or "application/octet-stream"
    raw_bytes = await file.read()
    output_bytes = b""
    try:
        validate_image(raw_bytes, content_type)
        output_bytes = process_image(raw_bytes, action)
    except (ImageTooLargeError, UnsupportedImageTypeError) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error("Image processing error: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
    finally:
        del raw_bytes
        gc.collect()

    return Response(content=output_bytes, media_type="image/png")


@app.post("/edit-image", tags=["Image"], summary="Edit image and return base64 PNG")
async def edit_image(
    file: UploadFile = File(...),
    action: str = Form(...),
    level: float | None = Form(default=None),
):
    """
    Lightweight editing endpoint that returns a base64-encoded PNG.
    Accepts the same *action* and *level* values as /image/process.
    ZDR: image bytes are deleted from memory after processing.
    """
    image_bytes: bytes | None = None
    try:
        image_bytes = await file.read()
        edited_bytes = process_image(image_bytes, action)

        # Convert to base64 so the frontend can display it inline
        b64_image = base64.b64encode(edited_bytes).decode("utf-8")

        return {
            "success": True,
            "image": f"data:image/png;base64,{b64_image}",
            "message": f"Image edited successfully ({action})",
        }

    except (ValueError, RuntimeError) as e:
        return {"success": False, "message": str(e)}
    except Exception as e:
        logger.error("edit-image error: %s", type(e).__name__)
        return {"success": False, "message": "An unexpected error occurred."}
    finally:
        if image_bytes is not None:
            del image_bytes
        gc.collect()

@app.post("/edit-image-natural")
async def edit_image_natural(
    file: UploadFile = File(...),
    message: str = Form(""),
    instruction: str = Form(""),
    cfg: Settings = Depends(get_settings),
):
    """
    Accept an image and a plain-English instruction.
    Detects the intended edit action and returns the processed image as
    a base64 PNG.

    Response shapes
    ---------------
    Edit recognised → { "type": "image", "image": "data:image/png;base64,…", "action": "<key>" }
    No action found → { "type": "text",  "response": "<hint message>" }

    ZDR: image bytes are deleted from memory after processing.
    """
    image_bytes = None
    inst = (instruction or message or "").strip()

    try:
        image_bytes = await file.read()

        # Advanced edit → Gemini
        gemini_key = os.getenv("GEMINI_API_KEY") or cfg.GEMINI_API_KEY
        if inst and is_advanced_edit(inst) and gemini_key:
            try:
                edited_bytes = await gemini_edit_image(image_bytes, inst)
                b64 = base64.b64encode(edited_bytes).decode("utf-8")
                return {
                    "type": "image",
                    "image": f"data:image/png;base64,{b64}",
                    "action": "gemini_edit",
                    "message": "Edited with Gemini",
                }
            except Exception as e:
                logger.error("Gemini edit failed: %s", e)
                # fall through to local

        action = detect_edit_action(inst)

        if not action:
            return {
                "type": "text",
                "response": (
                    "I can help you edit the image. Try saying things like:\n"
                    "- remove background\n"
                    "- make it grayscale\n"
                    "- sharpen this\n"
                    "- increase brightness"
                ),
            }

        # Process the image
        edited_bytes = process_image(image_bytes, action)
        b64_image = base64.b64encode(edited_bytes).decode("utf-8")

        return {
            "type": "image",
            "image": f"data:image/png;base64,{b64_image}",
            "action": action,
        }

    except Exception as e:
        return {
            "type": "text",
            "response": f"Sorry, I couldn't edit the image. Error: {str(e)}",
        }

    finally:
        # Zero Data Retention
        if image_bytes is not None:
            del image_bytes
        gc.collect()


# ── Document & Presentation Generation (AI-powered) ────────────────────────

@app.post("/generate-doc")
@app.post("/generate-document")
async def generate_document_endpoint(request: dict):
    topic = (request.get("topic") or "").strip()
    instructions = (request.get("instructions") or request.get("prompt") or topic).strip()
    if not topic and not instructions:
        return JSONResponse(
            status_code=400,
            content={"detail": "Topic or instructions required", "error": "Topic or instructions required", "private": True},
        )

    try:
        content = await generate_document_content(instructions)
        doc_bytes = create_document(
            title=content.get("title") or topic or "Document",
            sections=content.get("sections", []),
        )
        filename = (content.get("title") or topic or "SilentGPT_Document").replace(" ", "_") + ".docx"
        return Response(
            content=doc_bytes,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as exc:
        logger.error("Document generation failed: %s", exc)
        return JSONResponse(
            status_code=500,
            content={
                "detail": f"Document generation failed: {exc}",
                "error": str(exc),
                "private": True,
            },
        )
    finally:
        gc.collect()


@app.post("/generate-presentation")
async def generate_presentation_endpoint(request: dict):
    topic = (request.get("topic") or "").strip()
    instructions = (request.get("instructions") or request.get("prompt") or topic).strip()
    if not topic and not instructions:
        return JSONResponse(
            status_code=400,
            content={"detail": "Topic or instructions required", "error": "Topic or instructions required", "private": True},
        )

    try:
        content = await generate_presentation_content(instructions)
        ppt_bytes = create_presentation(
            title=content.get("title") or topic or "Presentation",
            slides_data=content.get("slides", []),
        )
        filename = (content.get("title") or topic or "SilentGPT_Presentation").replace(" ", "_") + ".pptx"
        return Response(
            content=ppt_bytes,
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as exc:
        logger.error("Presentation generation failed: %s", exc)
        return JSONResponse(
            status_code=500,
            content={
                "detail": f"Presentation generation failed: {exc}",
                "error": str(exc),
                "private": True,
            },
        )
    finally:
        gc.collect()


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


# ── Serve Static Frontend Files ───────────────────────────────────────────────
_parent_root = Path(__file__).resolve().parent.parent
_current_dir = Path(__file__).resolve().parent
ROOT_DIR = _parent_root if (_parent_root / "index.html").exists() else _current_dir


@app.get("/", include_in_schema=False)
async def serve_root():
    """Serve index.html at root."""
    index_file = ROOT_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    raise HTTPException(status_code=404, detail="index.html not found")


if ROOT_DIR.exists():
    app.mount("/", StaticFiles(directory=str(ROOT_DIR), html=True), name="static")

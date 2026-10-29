"""
SilentGPT Backend — ai.py
Hybrid AI Architecture:
  - Text & Document Generation (/chat, /generate-doc, PPT):
    Primary Provider: Groq API (llama-3.3-70b-versatile, llama-3.1-8b-instant).
    Failover: Google Gemini API (gemini-3.8-flash, etc.) on rate limits (429) or errors.
  - Image Generation (/generate-image):
    Routed exclusively through Google Gemini API.

Zero Data Retention:
  - Prompts and images are built in-memory and passed ephemerally.
  - No conversation history, prompts, or messages are logged or stored.
  - Memory references are freed immediately once functions return.
"""

import os
import json
import re
import httpx
import base64
import logging
from config import get_settings

logger = logging.getLogger("silentgpt")
settings = get_settings()

# System prompt that enforces SilentGPT's privacy persona.
_SYSTEM_PROMPT = """You are SilentGPT — a privacy-first AI assistant.

Rules:
1. Be concise, helpful, and natural.
2. If search results are provided, use them for accurate answers.
3. Do not mention data deletion, privacy policies, or system messages in every reply.
4. Never ask the user for personal information.
5. Answer normally like a helpful assistant.
"""


def _get_groq_client():
    key = os.getenv("GROQ_API_KEY", "").strip() or settings.GROQ_API_KEY.strip()
    if not key:
        return None
    try:
        from groq import AsyncGroq
        return AsyncGroq(api_key=key)
    except Exception as e:
        logger.warning("Could not initialize Groq Client: %s", e)
        return None


def _get_gemini_client():
    key = os.getenv("GEMINI_API_KEY", "").strip() or settings.GEMINI_API_KEY.strip()
    if not key:
        return None
    try:
        from google import genai
        return genai.Client(api_key=key)
    except Exception as e:
        logger.warning("Could not initialize google.genai Client: %s", e)
        return None


# ── Text generation (Hybrid Groq + Gemini Failover) ──────────────────────────

async def _generate_groq_response(prompt: str, model: str | None = None) -> tuple[str, str]:
    """Execute text generation via Groq API statelessly."""
    client = _get_groq_client()
    if not client:
        raise RuntimeError("GROQ_API_KEY not configured")

    candidate_models = [
        model if (model and "llama" in model.lower()) else settings.GROQ_MODEL,
        settings.GROQ_MODEL,
        settings.GROQ_FALLBACK_MODEL,
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
    ]
    seen = set()
    models_to_try = [m for m in candidate_models if m and not (m in seen or seen.add(m))]

    last_err = None
    for m in models_to_try:
        try:
            completion = await client.chat.completions.create(
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                model=m,
                temperature=0.7,
                max_tokens=2048,
            )
            if completion and completion.choices:
                content = completion.choices[0].message.content or ""
                if content.strip():
                    return content.strip(), m
        except Exception as e:
            last_err = e
            logger.warning("Groq model %s error: %s", m, type(e).__name__)
            continue

    raise RuntimeError(f"Groq text generation failed: {last_err}")


async def _generate_gemini_response(prompt: str, model: str | None = None) -> tuple[str, str]:
    """Execute text generation via Google Gemini API statelessly."""
    client = _get_gemini_client()
    if not client:
        raise RuntimeError("GEMINI_API_KEY not configured")

    from google.genai import types

    gemini_model = model if (model and "gemini" in model.lower()) else settings.GEMINI_MODEL
    candidate_models = [
        gemini_model,
        "gemini-3.8-flash",
        "gemini-2.5-flash",
        "gemini-1.5-flash",
        "gemini-2.0-flash",
    ]
    seen = set()
    models_to_try = [m for m in candidate_models if m and not (m in seen or seen.add(m))]

    last_err = None
    for model_name in models_to_try:
        try:
            config = types.GenerateContentConfig(
                system_instruction=_SYSTEM_PROMPT,
                temperature=0.7,
            )
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config,
            )
            if response and response.text:
                return response.text.strip(), model_name
        except Exception as e:
            last_err = e
            logger.warning("Gemini model %s failed: %s", model_name, type(e).__name__)
            continue

    raise RuntimeError(f"Gemini text generation failed: {last_err}")


async def _generate_ollama_response(prompt: str, model: str | None = None) -> str:
    """Local offline Ollama generation fallback."""
    model = model or settings.OLLAMA_MODEL

    options = {
        "temperature": 0.7,
        "top_p": 0.9,
        "num_predict": 1024,
    }
    if any(tag in model.lower() for tag in ["26b", "27b", "30b", "34b", "70b"]):
        options["num_gpu"] = 0

    chat_payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "options": options,
    }

    async with httpx.AsyncClient(
        base_url=settings.OLLAMA_BASE_URL,
        timeout=180.0,
    ) as client:
        try:
            resp = await client.post("/api/chat", json=chat_payload)
            resp.raise_for_status()
            data = resp.json()
            return data.get("message", {}).get("content", "").strip()
        except Exception:
            fallback_options = dict(options)
            fallback_options["num_gpu"] = 0
            chat_payload["options"] = fallback_options
            try:
                resp = await client.post("/api/chat", json=chat_payload)
                resp.raise_for_status()
                data = resp.json()
                return data.get("message", {}).get("content", "").strip()
            except Exception:
                gen_payload = {
                    "model": model,
                    "system": _SYSTEM_PROMPT,
                    "prompt": prompt,
                    "stream": False,
                    "options": fallback_options,
                }
                resp = await client.post("/api/generate", json=gen_payload)
                resp.raise_for_status()
                data = resp.json()
                return data.get("response", "").strip()


async def generate_response_with_model(prompt: str, model: str | None = None) -> tuple[str, str]:
    """
    Stateless text generation using hybrid architecture:
      1. Primary: Groq API (llama-3.3-70b-versatile / llama-3.1-8b-instant).
      2. Failover: Google Gemini API (gemini-3.8-flash, etc.) on rate limits or errors.
      3. Offline Fallback: Local Ollama (if available).
    """
    has_groq = bool(os.getenv("GROQ_API_KEY", "").strip() or settings.GROQ_API_KEY.strip())
    has_gemini = bool(os.getenv("GEMINI_API_KEY", "").strip() or settings.GEMINI_API_KEY.strip())

    # Step 1: Try Groq as primary text provider
    if has_groq:
        try:
            return await _generate_groq_response(prompt, model=model)
        except Exception as exc:
            logger.warning("Groq text generation failed: %s. Initiating Gemini failover...", type(exc).__name__)

    # Step 2: Graceful failover to Gemini
    if has_gemini:
        try:
            return await _generate_gemini_response(prompt, model=model)
        except Exception as exc:
            logger.warning("Gemini text failover failed: %s", type(exc).__name__)

    # Step 3: Local Ollama fallback (pure offline mode only when neither cloud API is configured)
    if not (has_groq or has_gemini) and await is_ollama_healthy():
        try:
            ans = await _generate_ollama_response(prompt, model=model)
            return ans, settings.OLLAMA_MODEL
        except Exception as exc:
            logger.warning("Ollama fallback failed: %s", type(exc).__name__)

    # Step 4: All providers failed
    raise RuntimeError("Both Groq and Gemini APIs failed. Please check your API keys or rate limits.")


async def generate_response(prompt: str, model: str | None = None) -> str:
    """Compatibility wrapper returning generated text string."""
    text, _ = await generate_response_with_model(prompt, model=model)
    return text


# ── Vision / Image analysis ───────────────────────────────────────────────────

IMAGE_ANALYSIS_PROMPT = """Analyze this image carefully and respond in this structure:

1. **What it is** — brief identification
2. **Key details** — important elements, text, logos, people, objects
3. **Meaning / purpose** — what this image is trying to communicate
4. **Quality check** — blur, lighting, contrast, clutter, readability issues
5. **Editing advice** — only if useful. Pick from:
   - remove background
   - increase brightness / contrast
   - sharpen
   - crop
   - no edit needed

Be clear and practical. Do not only list colors and shapes."""


async def analyse_image(
    image_bytes: bytes,
    instruction: str | None = None,
    model: str | None = None,
) -> str:
    """
    Send an image to Gemini (primary) or Ollama (fallback) for vision analysis.
    ZDR NOTE: image_bytes is NOT written to disk and discarded after request.
    """
    clean_instr = (instruction or "").strip().lower().rstrip(".?!")
    generic_prompts = {
        "", "describe this image in detail", "describe this image",
        "describe image", "what is this", "what is this image",
        "what is this picture", "what is in this image",
        "analyze this image", "analyze this", "explain this image",
        "tell me about this image",
    }
    prompt_text = IMAGE_ANALYSIS_PROMPT if clean_instr in generic_prompts else (instruction or "Describe this image.").strip()

    has_gemini = bool(os.getenv("GEMINI_API_KEY", "").strip() or settings.GEMINI_API_KEY.strip())
    if has_gemini:
        client = _get_gemini_client()
        if client:
            from google.genai import types
            for m in ["gemini-3.8-flash", "gemini-2.5-flash-image", "gemini-3.1-flash-image"]:
                try:
                    resp = client.models.generate_content(
                        model=m,
                        contents=[
                            prompt_text,
                            types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
                        ],
                        config=types.GenerateContentConfig(
                            system_instruction=_SYSTEM_PROMPT,
                            temperature=0.5,
                        ),
                    )
                    if resp and resp.text:
                        return resp.text.strip()
                except Exception as e:
                    logger.warning("Gemini vision %s failed: %s", m, e)
                    continue

    # Fallback to Ollama vision if available
    return await _analyse_image_ollama(image_bytes, prompt_text, model=model)


async def _analyse_image_ollama(image_bytes: bytes, prompt_text: str, model: str | None = None) -> str:
    model = model or settings.OLLAMA_VISION_MODEL
    b64_image = base64.b64encode(image_bytes).decode("utf-8")

    payload = {
        "model": model,
        "system": _SYSTEM_PROMPT,
        "prompt": prompt_text,
        "images": [b64_image],
        "stream": False,
        "options": {
            "temperature": 0.5,
            "num_predict": 512,
        },
    }

    async with httpx.AsyncClient(
        base_url=settings.OLLAMA_BASE_URL,
        timeout=120.0,
    ) as client:
        resp = await client.post("/api/generate", json=payload)
        resp.raise_for_status()
        data = resp.json()

    del b64_image
    return data.get("response", "").strip()


# ── Health checks ─────────────────────────────────────────────────────────────

async def is_ollama_healthy() -> bool:
    """Ping Ollama to verify if it is running and reachable."""
    try:
        async with httpx.AsyncClient(
            base_url=settings.OLLAMA_BASE_URL, timeout=2.0
        ) as client:
            resp = await client.get("/api/tags")
            return resp.status_code == 200
    except Exception:
        return False


def is_groq_healthy() -> bool:
    """Check whether Groq API key is configured."""
    return bool(os.getenv("GROQ_API_KEY", "").strip() or settings.GROQ_API_KEY.strip())


def is_gemini_healthy() -> bool:
    """Check whether Gemini API key is configured."""
    return bool(os.getenv("GEMINI_API_KEY", "").strip() or settings.GEMINI_API_KEY.strip())


# ── Document & Presentation Content Generation ───────────────────────────────

async def generate_document_content(instructions: str) -> dict:
    prompt = f"""Create a well-structured document based on this user request:

USER REQUEST:
{instructions}

Return ONLY valid JSON in this exact format:
{{
  "title": "Document Title",
  "sections": [
    {{
      "heading": "Section heading",
      "content": "Section body text..."
    }}
  ]
}}

Rules:
- Follow the user's requirements exactly (tone, length, audience, structure).
- If user asks for concise/short: keep each section to 1 short paragraph.
- If user asks for detailed/paragraphs: write fuller paragraphs (2–4 per major section).
- If user asks academic/formal: use formal language.
- If user asks simple/beginner: use simple language and examples.
- If user lists sections to include, include them.
- Make 4–8 sections unless user specifies otherwise.
- No text outside the JSON.
"""
    raw = await generate_response(prompt)
    return _extract_json(raw)


async def generate_presentation_content(instructions: str) -> dict:
    prompt = f"""Create a professional presentation based on this user request:

USER REQUEST:
{instructions}

Return ONLY valid JSON in this exact format:
{{
  "title": "Presentation Title",
  "slides": [
    {{
      "title": "Slide title",
      "points": ["Bullet 1", "Bullet 2", "Bullet 3"]
    }}
  ]
}}

Rules:
- Follow the user's requirements exactly (tone, slide count, audience, style).
- If user asks concise/short: max 3 short bullets per slide.
- If user asks detailed: up to 5 bullets, still short enough for slides (not paragraphs).
- If user specifies number of slides (e.g. 5 slides), respect that count.
- If user asks for beginners: simple wording and examples.
- If user asks formal/academic: more precise wording.
- Default: 5–8 slides if not specified.
- No text outside the JSON.
"""
    raw = await generate_response(prompt)
    return _extract_json(raw)


def _extract_json(text: str) -> dict:
    """Safely extract JSON from the model response."""
    try:
        return json.loads(text)
    except:
        match = re.search(r'\{[\s\S]*\}', text)
        if match:
            try:
                return json.loads(match.group())
            except:
                pass
    return {"title": "Generated Content", "sections": [], "slides": []}

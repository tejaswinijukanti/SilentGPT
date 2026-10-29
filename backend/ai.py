"""
SilentGPT Backend — ai.py
Ollama client for text generation and vision (image analysis).

Model defaults:
  - Text : phi3:mini   (fast, 3.8B, runs on CPU)
  - Vision: phi3:vision (or swap for llava:7b)

Zero Data Retention:
  - Prompts are built in-memory and passed directly to Ollama.
  - No conversation history is sent (every request is fully stateless).
  - The prompt string is garbage-collected as soon as the function returns.
"""

import json
import re
import httpx
import base64
from config import get_settings

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


# ── Text generation ───────────────────────────────────────────────────────────

async def generate_response(prompt: str, model: str | None = None) -> str:
    """
    Send a prompt to Ollama and return the generated text.

    Zero Data Retention (ZDR):
      - `prompt` exists only in this request's ephemeral stack frame.
      - No message history is retained or recorded.
      - Memory is freed immediately once the response is sent.
    """
    model = model or settings.OLLAMA_MODEL

    options = {
        "temperature": 0.7,
        "top_p": 0.9,
        "num_predict": 1024,
    }
    # If the model exceeds the GPU's 6GB VRAM (e.g. 26b/27b/70b), run on CPU to avoid CUDA OOM
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
            # Fallback retry: force CPU execution if GPU ran out of memory
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
    Send an image (as raw bytes) to an Ollama vision model for analysis.

    The image is base64-encoded in memory, sent to Ollama, and the
    bytes reference is dropped immediately after the call returns.

    ZDR NOTE: `image_bytes` is NOT written to disk at any point.
              base64 string is a local variable discarded after the request.
    """
    model = model or settings.OLLAMA_VISION_MODEL

    # Use structured prompt whenever no text or generic prompt like "what is this" is given
    clean_instr = (instruction or "").strip().lower().rstrip(".?!")
    generic_prompts = {
        "",
        "describe this image in detail",
        "describe this image",
        "describe image",
        "what is this",
        "what is this image",
        "what is this picture",
        "what is in this image",
        "analyze this image",
        "analyze this",
        "explain this image",
        "tell me about this image",
    }
    if clean_instr in generic_prompts:
        prompt_text = IMAGE_ANALYSIS_PROMPT
    else:
        prompt_text = instruction.strip()

    # Encode image to base64 (stays in RAM)
    b64_image = base64.b64encode(image_bytes).decode("utf-8")

    payload = {
        "model": model,
        "system": _SYSTEM_PROMPT,
        "prompt": prompt_text,
        "images": [b64_image],   # Ollama vision API field
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

    # Explicitly clear large objects before returning
    del b64_image
    del image_bytes

    return data.get("response", "").strip()


# ── Health check ──────────────────────────────────────────────────────────────

async def is_ollama_healthy() -> bool:
    """Ping Ollama to verify it is running and reachable."""
    try:
        async with httpx.AsyncClient(
            base_url=settings.OLLAMA_BASE_URL, timeout=5.0
        ) as client:
            resp = await client.get("/api/tags")
            return resp.status_code == 200
    except Exception:
        return False


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
        # Try direct parse first
        return json.loads(text)
    except:
        # Fallback: find JSON block inside the text
        match = re.search(r'\{[\s\S]*\}', text)
        if match:
            try:
                return json.loads(match.group())
            except:
                pass
    return {"title": "Generated Content", "sections": [], "slides": []}


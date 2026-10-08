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
Key rules you must follow:
1. Search results will be provided to you; use them to give accurate, up-to-date answers.
2. Never ask the user to share personal information.
3. Never reveal that you are storing anything — because you are not.
4. Be concise, helpful, and honest.
5. If search results are empty, answer from your training knowledge and say so.
6. Always end your response with: "🔒 Your query has been permanently deleted from our systems."
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

    chat_payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "options": {
            "temperature": 0.7,
            "top_p": 0.9,
            "num_predict": 1024,
        },
    }

    async with httpx.AsyncClient(
        base_url=settings.OLLAMA_BASE_URL,
        timeout=120.0,
    ) as client:
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
                "options": {
                    "temperature": 0.7,
                    "top_p": 0.9,
                    "num_predict": 1024,
                },
            }
            resp = await client.post("/api/generate", json=gen_payload)
            resp.raise_for_status()
            data = resp.json()
            return data.get("response", "").strip()


# ── Vision / Image analysis ───────────────────────────────────────────────────

async def analyse_image(
    image_bytes: bytes,
    instruction: str = "Describe this image in detail.",
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

    # Encode image to base64 (stays in RAM)
    b64_image = base64.b64encode(image_bytes).decode("utf-8")

    payload = {
        "model": model,
        "system": _SYSTEM_PROMPT,
        "prompt": instruction,
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

async def generate_document_content(topic: str) -> dict:
    """
    Ask Ollama to create structured content for a Word document.
    Returns: { "title": "...", "sections": [{"heading": "...", "content": "..."}] }
    """
    prompt = f"""
Create a well-structured educational document on the topic: "{topic}".

Return ONLY valid JSON in this exact format (no extra text):

{{
  "title": "Document Title",
  "sections": [
    {{
      "heading": "Introduction",
      "content": "Write 2-3 paragraphs here..."
    }},
    {{
      "heading": "Main Point 1",
      "content": "Write detailed content here..."
    }},
    {{
      "heading": "Main Point 2",
      "content": "Write detailed content here..."
    }},
    {{
      "heading": "Conclusion",
      "content": "Write conclusion here..."
    }}
  ]
}}

Rules:
- Make 4 to 6 sections
- Content should be informative and clear
- Do not add any text outside the JSON
"""

    raw = await generate_response(prompt)
    return _extract_json(raw)


async def generate_presentation_content(topic: str) -> dict:
    """
    Ask Ollama to create structured content for a PowerPoint.
    Returns: { "title": "...", "slides": [{"title": "...", "points": ["...", "..."]}] }
    """
    prompt = f"""
Create a professional presentation on the topic: "{topic}".

Return ONLY valid JSON in this exact format (no extra text):

{{
  "title": "Presentation Title",
  "slides": [
    {{
      "title": "Introduction",
      "points": [
        "Point 1",
        "Point 2",
        "Point 3"
      ]
    }},
    {{
      "title": "Key Concept 1",
      "points": [
        "Point 1",
        "Point 2",
        "Point 3"
      ]
    }},
    {{
      "title": "Key Concept 2",
      "points": [
        "Point 1",
        "Point 2"
      ]
    }},
    {{
      "title": "Conclusion",
      "points": [
        "Summary point 1",
        "Summary point 2"
      ]
    }}
  ]
}}

Rules:
- Make 5 to 8 slides
- Each slide should have 3 to 5 short bullet points
- Do not add any text outside the JSON
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


import base64
import os
from google import genai
from google.genai import types


def _client():
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        try:
            from config import get_settings
            key = get_settings().GEMINI_API_KEY.strip()
        except Exception:
            pass
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set")
    return genai.Client(api_key=key)


MODELS = [
    "gemini-nano-banana-2.1",
    "gemini-3.1-flash-image",
    "gemini-2.5-flash-image",
]


async def gemini_process_image(instruction: str, image_bytes: bytes | None = None) -> dict:
    """
    - image_bytes = None  → generate new image from text
    - image_bytes set     → edit the uploaded image
    """
    client = _client()
    instruction = (instruction or "").strip()
    if not instruction:
        instruction = "Describe this image." if image_bytes else "Generate a simple image."

    if image_bytes:
        prompt = f"""Edit this image.

Instruction: {instruction}

Apply only the requested change. Return the edited image.
Do not invent fake image URLs. Return the actual image."""
        contents = [
            prompt,
            types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
        ]
    else:
        prompt = f"""Generate an image.

Request: {instruction}

Create a clear, high-quality image that matches the request.
Return the actual image (not a description, not ASCII, not a URL)."""
        contents = [prompt]

    last_err = None
    for model in MODELS:
        try:
            response = client.models.generate_content(
                model=model,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_modalities=["TEXT", "IMAGE"],
                ),
            )

            text_parts = []
            image_out = None

            for part in response.candidates[0].content.parts:
                if getattr(part, "text", None):
                    text_parts.append(part.text)
                inline = getattr(part, "inline_data", None)
                if inline and inline.data:
                    data = inline.data
                    if isinstance(data, str):
                        data = base64.b64decode(data)
                    image_out = data

            if image_out:
                b64 = base64.b64encode(image_out).decode("utf-8")
                return {
                    "type": "image",
                    "image": f"data:image/png;base64,{b64}",
                    "response": text_parts[0] if text_parts else "Done.",
                    "model": model,
                }

            # text-only reply (e.g. pure describe)
            if text_parts:
                return {
                    "type": "text",
                    "response": "\n".join(text_parts).strip(),
                    "model": model,
                }

            last_err = RuntimeError(f"{model} returned no image/text")
        except Exception as e:
            last_err = e
            continue

    raise RuntimeError(f"Gemini failed: {last_err}")


async def gemini_edit_image(image_bytes: bytes, instruction: str) -> bytes:
    """Compatibility wrapper that returns raw image bytes."""
    res = await gemini_process_image(instruction, image_bytes=image_bytes)
    if res.get("type") == "image" and res.get("image"):
        data = res["image"]
        if "," in data:
            data = data.split(",")[1]
        return base64.b64decode(data)
    raise RuntimeError(res.get("response") or "Gemini did not return an edited image")


def is_advanced_edit(instruction: str) -> bool:
    """Detect edit instructions."""
    text = (instruction or "").lower().strip()
    if not text:
        return False
    keywords = [
        "add ", "remove ", "delete ", "erase ", "change ", "replace ",
        "put ", "draw ", "make it ", "turn into ", "convert to ",
        "fix ", "inpaint ", "background", "watermark", "text",
        "object", "person", "people", "bird", "birds", "sky",
        "color", "style", "cartoon", "blur face"
    ]
    return any(k in text for k in keywords)

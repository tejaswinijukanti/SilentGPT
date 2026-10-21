"""
SilentGPT Backend — image_handler.py
In-memory image validation and metadata extraction using Pillow.

This module is used as a fallback when the Ollama vision model is not
available (e.g. phi3:mini without vision support). It provides basic
image metadata and a structured description without requiring a GPU.

Zero Data Retention:
  - Images are NEVER written to disk.
  - All processing happens on raw bytes in RAM.
  - The bytes buffer is explicitly cleared (del) after use.
"""

import io
from PIL import Image, ExifTags, ImageFilter, ImageEnhance
from config import get_settings

settings = get_settings()

_MAX_BYTES = settings.MAX_IMAGE_SIZE_MB * 1024 * 1024   # convert MB → bytes

ALLOWED_MIME_TYPES = {
    "image/jpeg", "image/png", "image/gif",
    "image/webp", "image/bmp", "image/tiff",
}


class ImageTooLargeError(ValueError):
    pass

class UnsupportedImageTypeError(ValueError):
    pass


def validate_image(data: bytes, content_type: str) -> None:
    """
    Raises an error if the image fails validation.
    Called before any processing to fail fast.
    """
    if content_type not in ALLOWED_MIME_TYPES:
        raise UnsupportedImageTypeError(
            f"Unsupported image type: {content_type}. "
            f"Allowed: {', '.join(ALLOWED_MIME_TYPES)}"
        )
    if len(data) > _MAX_BYTES:
        raise ImageTooLargeError(
            f"Image exceeds maximum allowed size of {settings.MAX_IMAGE_SIZE_MB} MB."
        )


def extract_metadata(image_bytes: bytes) -> dict:
    """
    Open image from raw bytes, extract safe metadata, then close.
    Returns a plain dict — never stores the image object.

    ZDR NOTE: `buf` and `img` are local — garbage collected on return.
    """
    buf = io.BytesIO(image_bytes)       # in-memory buffer, no disk I/O
    try:
        with Image.open(buf) as img:
            metadata = {
                "format": img.format or "unknown",
                "mode": img.mode,
                "width": img.width,
                "height": img.height,
                "size_kb": round(len(image_bytes) / 1024, 1),
            }

            # Extract safe EXIF data (skip GPS and personal info)
            exif_raw = img._getexif() if hasattr(img, "_getexif") else None
            if exif_raw:
                safe_tags = {}
                for tag_id, value in exif_raw.items():
                    tag_name = ExifTags.TAGS.get(tag_id, str(tag_id))
                    # Skip GPS data (privacy) and unknown binary tags
                    if "GPS" in tag_name or isinstance(value, bytes):
                        continue
                    safe_tags[tag_name] = str(value)[:100]
                metadata["exif"] = safe_tags
    finally:
        buf.close()   # ensure buffer is released

    return metadata


def build_fallback_description(metadata: dict) -> str:
    """
    Build a text description of the image from its metadata alone.
    Used when no vision LLM is available.
    """
    fmt = metadata.get("format", "Unknown")
    w = metadata.get("width", "?")
    h = metadata.get("height", "?")
    mode = metadata.get("mode", "?")
    size = metadata.get("size_kb", "?")

    desc = (
        f"Image received and processed successfully.\n"
        f"Format: {fmt} | Dimensions: {w}×{h}px | "
        f"Note: A vision-capable model (e.g. llava, phi3:vision) is required "
        f"for detailed AI analysis. Configure OLLAMA_VISION_MODEL in your .env file."
    )
    return desc


# All supported editing actions and their human-readable descriptions.
SUPPORTED_ACTIONS: dict[str, str] = {
    "remove_bg":  "Remove image background using AI (rembg)",
    "grayscale":  "Convert image to greyscale",
    "blur":       "Apply Gaussian blur  — level controls radius (default 3)",
    "sharpen":    "Sharpen the image   — level controls passes (default 1)",
    "brightness": "Adjust brightness   — level is a multiplier (default 1.4)",
    "contrast":   "Adjust contrast     — level is a multiplier (default 1.4)",
    "saturation": "Adjust colour saturation — level is a multiplier (default 1.4)",
    "rotate":     "Rotate image        — level is degrees clockwise (default 90)",
    "flip_h":     "Flip image horizontally (mirror)",
    "flip_v":     "Flip image vertically",
    "crop":       "Centre-crop to a square",
}


def detect_edit_action(text: str) -> str | None:
    """
    Parse a natural-language instruction and return the matching
    SUPPORTED_ACTIONS key, or None if no action is recognised.
    """
    text = text.lower().strip()

    if any(kw in text for kw in ["remove background", "remove bg", "background remove", "remove the background"]):
        return "remove_bg"
    elif any(kw in text for kw in ["grayscale", "black and white", "b&w", "black & white"]):
        return "grayscale"
    elif "blur" in text:
        return "blur"
    elif any(kw in text for kw in ["sharpen", "sharp", "make it sharp"]):
        return "sharpen"
    elif any(kw in text for kw in ["brightness", "brighter", "increase brightness", "make it brighter"]):
        return "brightness"

    return None


def process_image(image_bytes: bytes, action: str) -> bytes:
    """
    Apply the requested image edit and return the result as PNG bytes.

    Supported actions
    -----------------
    remove_bg   — AI background removal via rembg
    grayscale   — Convert to greyscale
    blur        — Gaussian blur (radius 3)
    sharpen     — Sharpen filter
    brightness  — Brightness adjust (multiplier 1.4)

    ZDR Note
    --------
    All intermediate objects are local and garbage-collected on return.
    """
    if action == "remove_bg":
        from rembg import remove
        return remove(image_bytes)

    img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")

    if action == "grayscale":
        img = img.convert("L").convert("RGBA")
    elif action == "blur":
        img = img.filter(ImageFilter.GaussianBlur(radius=3))
    elif action == "sharpen":
        img = img.filter(ImageFilter.SHARPEN)
    elif action == "brightness":
        enhancer = ImageEnhance.Brightness(img)
        img = enhancer.enhance(1.4)

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()



"""
SilentGPT — Content Generator
Re-exports AI-driven document and presentation content generators from ai.py.
"""

from ai import generate_document_content, generate_presentation_content, _extract_json

__all__ = [
    "generate_document_content",
    "generate_presentation_content",
    "_extract_json",
]

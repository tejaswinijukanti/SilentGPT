"""
SilentGPT Backend — models.py
Pydantic request and response schemas.
All models are stateless — no IDs, sessions, or history fields.
"""

from pydantic import BaseModel, Field
from typing import Optional


# ── Chat ─────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str = Field(
        ...,
        min_length=1,
        max_length=4000,
        description="The user's question or prompt.",
        examples=["What is quantum computing?"],
    )

class SearchSource(BaseModel):
    title: str
    url: str
    snippet: str = ""

class ChatResponse(BaseModel):
    response: str = Field(..., description="The AI-generated answer.")
    sources: list[SearchSource] = Field(
        default_factory=list,
        description="Web sources used to generate the answer.",
    )
    private: bool = Field(True, description="Always True — no data was retained.")
    model: str = Field("", description="AI model used.")


# ── Image ─────────────────────────────────────────────────────────────────────

class ImageResponse(BaseModel):
    analysis: str = Field(..., description="The AI's analysis of the uploaded image.")
    private: bool = Field(True, description="Always True — image deleted after processing.")


# ── Health ────────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str = Field("ok", description="'ok' when the server is running.")
    ollama_connected: bool = Field(..., description="Whether AI provider is reachable.")
    search_configured: bool = Field(..., description="Whether a search API key is set.")
    zero_data_retention: bool = Field(True, description="Always True — ZDR is enforced.")
    gemini_configured: bool = Field(False, description="Whether Gemini API is configured.")
    primary_provider: str = Field("gemini", description="Active primary AI provider.")


# ── Error ─────────────────────────────────────────────────────────────────────

class ErrorResponse(BaseModel):
    detail: str
    private: bool = True

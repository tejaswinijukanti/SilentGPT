"""
SilentGPT Backend — search.py
Web search integration.

Supports two providers (configure via SEARCH_PROVIDER env var):
  - Tavily  (recommended, AI-optimised)  https://tavily.com
  - Serper  (Google results via API)      https://serper.dev

Zero Data Retention: search queries are never logged or stored.
Results live only in the coroutine's local scope and are discarded
as soon as the calling endpoint sends its response.
"""

import httpx
from tavily import AsyncTavilyClient
from models import SearchSource
from config import get_settings

settings = get_settings()


# ── Tavily ────────────────────────────────────────────────────────────────────

async def _search_tavily(query: str) -> list[SearchSource]:
    """
    Calls the Tavily Search API using the official Tavily SDK
    and returns a list of SearchSource objects.
    Tavily is AI-optimised: it returns clean snippets ideal for LLM prompts.
    """
    client = AsyncTavilyClient(api_key=settings.TAVILY_API_KEY)
    response = await client.search(
        query=query,
        search_depth="basic",
        max_results=settings.SEARCH_MAX_RESULTS,
        include_answer=False,
    )

    sources: list[SearchSource] = []
    for r in response.get("results", []):
        sources.append(
            SearchSource(
                title=r.get("title") or "",
                url=r.get("url") or "",
                snippet=(r.get("content") or "")[:500],   # cap snippet length
            )
        )
    return sources


# ── Serper ────────────────────────────────────────────────────────────────────

async def _search_serper(query: str) -> list[SearchSource]:
    """
    Calls the Serper (Google) Search API.
    Use this as a fallback or alternative to Tavily.
    """
    headers = {
        "X-API-KEY": settings.SERPER_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {"q": query, "num": settings.SEARCH_MAX_RESULTS}

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            "https://google.serper.dev/search",
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

    sources: list[SearchSource] = []
    for r in data.get("organic", []):
        sources.append(
            SearchSource(
                title=r.get("title", ""),
                url=r.get("link", ""),
                snippet=r.get("snippet", "")[:500],
            )
        )
    return sources


# ── Public interface ──────────────────────────────────────────────────────────

async def search_web(query: str) -> list[SearchSource]:
    """
    Dispatches to the configured search provider.
    Returns an empty list if no API key is set or on error (graceful degradation).

    ZDR NOTE: The query string is used only within this function call.
              It is never written to disk, a database, or a log file.
    """
    provider = settings.SEARCH_PROVIDER.lower()

    if provider == "tavily" and settings.TAVILY_API_KEY:
        try:
            return await _search_tavily(query)
        except Exception:
            pass

    if provider == "serper" and settings.SERPER_API_KEY:
        try:
            return await _search_serper(query)
        except Exception:
            pass

    # Fallback: try the other provider automatically
    if settings.TAVILY_API_KEY:
        try:
            return await _search_tavily(query)
        except Exception:
            pass
    if settings.SERPER_API_KEY:
        try:
            return await _search_serper(query)
        except Exception:
            pass

    # No key configured or error occurred — return empty list
    return []


def format_sources_for_prompt(sources: list[SearchSource]) -> str:
    """
    Converts search results into a compact text block to inject into
    the Ollama prompt. Keeps token count low.
    """
    if not sources:
        return ""

    lines = ["[Web Search Results]"]
    for i, s in enumerate(sources, 1):
        lines.append(f"{i}. {s.title}")
        if s.snippet:
            lines.append(f"   {s.snippet}")
        lines.append(f"   Source: {s.url}")
    return "\n".join(lines)

# SilentGPT — Backend

A **privacy-first**, fully stateless FastAPI backend for the SilentGPT AI chatbot.

> **Zero Data Retention** — no messages, images, or queries are ever stored on disk or in a database. All data lives only in RAM for the duration of a single request and is discarded immediately after the response is sent.

---

## Project Structure

```
backend/
├── main.py            # FastAPI app, CORS, all routes
├── config.py          # Settings (loaded from .env)
├── models.py          # Pydantic request/response schemas
├── search.py          # Web search — Tavily & Serper
├── ai.py              # Ollama client (text + vision)
├── image_handler.py   # In-memory image validation & metadata
├── requirements.txt
├── .env.example       # Copy this to .env and fill in your keys
└── README.md
```

---

## Prerequisites

| Dependency | Version | Purpose |
|---|---|---|
| Python | ≥ 3.11 | Runtime |
| [Ollama](https://ollama.com) | latest | Local LLM inference |
| Tavily or Serper API key | — | Web search |

---

## Quick Start

### 1. Install Ollama and pull the model

```bash
# Install Ollama (Windows / Mac / Linux)
# → https://ollama.com/download

# Pull the default text model
ollama pull phi3:mini

# (Optional) Pull vision model for image analysis
ollama pull phi3:vision
# or
ollama pull llava:7b
```

### 2. Clone / navigate to the backend folder

```bash
cd backend
```

### 3. Create a virtual environment

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# Mac / Linux
source .venv/bin/activate
```

### 4. Install dependencies

```bash
pip install -r requirements.txt
```

### 5. Configure environment variables

```bash
# Copy the template
cp .env.example .env

# Open .env and fill in:
#   TAVILY_API_KEY   — get free key at https://tavily.com
#   OLLAMA_MODEL     — default: phi3:mini
```

### 6. Start the server

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at **http://localhost:8000**

---

### Alternative: Run with Docker 🐳

If you prefer using Docker instead of manual Python setup:

```bash
# From the project root:
docker compose up --build
```
- **Backend API**: http://localhost:8000 (Swagger docs at http://localhost:8000/docs)
- **Frontend UI**: http://localhost:3000
- *Note: Docker is configured to automatically communicate with Ollama running on your host machine via `host.docker.internal:11434`.*

---

## API Endpoints

### `GET /health`
Check server status.

```bash
curl http://localhost:8000/health
```

```json
{
  "status": "ok",
  "ollama_connected": true,
  "search_configured": true,
  "zero_data_retention": true
}
```

---

### `POST /chat`
Send a message and receive an AI response backed by live web search.

**Request**
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What is quantum computing?"}'
```

**Response**
```json
{
  "response": "Quantum computing uses quantum bits (qubits)... 🔒 Your query has been permanently deleted from our systems.",
  "sources": [
    {
      "title": "What Is Quantum Computing? | IBM",
      "url": "https://www.ibm.com/topics/quantum-computing",
      "snippet": "Quantum computing is a rapidly-emerging technology..."
    }
  ],
  "private": true,
  "model": "phi3:mini"
}
```

---

### `POST /image`
Upload an image for AI analysis.

**Request**
```bash
curl -X POST http://localhost:8000/image \
  -F "file=@/path/to/photo.jpg" \
  -F "instruction=What objects can you see in this image?"
```

**Response**
```json
{
  "analysis": "The image shows a mountainous landscape with snow-capped peaks... 🔒 Image has been permanently deleted from our systems.",
  "private": true
}
```

---

## Frontend Integration (JavaScript)

```javascript
const API_URL = window.location.origin;

// ── Chat ─────────────────────────────────────────────────────
async function sendMessage(userMessage) {
  const res = await fetch(`${API_URL}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message: userMessage }),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = await res.json();
  return data.response;   // AI answer
}

// ── Image ────────────────────────────────────────────────────
async function analyseImage(file, instruction = "Describe this image.") {
  const form = new FormData();
  form.append("file", file);
  form.append("instruction", instruction);

  const res = await fetch(`${API_URL}/image`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = await res.json();
  return data.analysis;
}
```

---

## Zero Data Retention — How It Works

| Layer | What happens |
|---|---|
| **Database** | None used. No SQLite, no Redis, no cloud DB. |
| **Disk** | Images are never written to disk. All bytes stay in RAM. |
| **Logs** | Server events are logged (startup, errors) but **user message content is never logged**. |
| **Memory** | Local variables (`prompt`, `image_bytes`) are explicitly `del`-eted in `finally` blocks after every request. |
| **Ollama** | Ollama is stateless by default. No conversation history is sent — each request is a fresh prompt. |
| **Search** | The search query is a local variable. Tavily/Serper do not associate it with any user identity from our side. |

---

## Environment Variables Reference

| Variable | Default | Description |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_MODEL` | `phi3:mini` | Text generation model |
| `OLLAMA_VISION_MODEL` | `phi3:vision` | Vision model for images |
| `SEARCH_PROVIDER` | `tavily` | `tavily` or `serper` |
| `TAVILY_API_KEY` | _(empty)_ | Tavily API key |
| `SERPER_API_KEY` | _(empty)_ | Serper API key |
| `SEARCH_MAX_RESULTS` | `5` | Search results injected into prompt |
| `ALLOWED_ORIGINS` | `["*"]` | CORS origins (set to frontend URL in prod) |
| `MAX_IMAGE_SIZE_MB` | `10` | Max image upload size |

---

## Interactive API Docs

Swagger UI: http://localhost:8000/docs  
ReDoc: http://localhost:8000/redoc

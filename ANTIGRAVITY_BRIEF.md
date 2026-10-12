# SilentGPT — Rebuild Brief (for Antigravity agents)

Place this file at the repo root. Treat it as the source of truth. If the UI needs something the API contract below lacks, add it to the contract first, then build.

## 0. Product principles
1. **Private by construction.** Nothing user-generated is stored server-side. The UI proves this instead of shouting it.
2. **Honest claims only.** Never write "end-to-end encrypted", "cryptographically erased" or "no third parties". Allowed: "Not stored on our server", "Runs on local models", "Never written to disk or logs". When web search is used, disclose it (Tavily receives the search query).
3. **Calm and fast.** Streaming first. Perceived latency under 300 ms. One ambient effect only.
4. **No third-party requests at runtime.** Self-host fonts and libraries. No CDNs, no analytics.

## 1. Stack decisions
- Frontend: **vanilla HTML/CSS/ES modules, no framework, no build step**. Folder `frontend/` (the backend serves ONLY this folder, never the repo root).
- Vendored locally in `frontend/vendor/`: `marked`, `DOMPurify`, `highlight.js` (core + few languages).
- Fonts (self-hosted, WOFF2, OFL): **Geist** (UI) and **Geist Mono** (code).
- State lives in memory only. History lives in JS memory and is lost on refresh. This is a feature; say so in the UI.

## 2. Design system

**Concept:** "Quiet room". Near-black, one violet accent, generous space, soft edges. It should feel like a private tool, not a sci-fi toy. Remove matrix rain and wave canvases.

### Tokens (`css/tokens.css`)
```css
:root{
  --bg:#0b0b10; --surface:#12121a; --surface-2:#191924; --line:#262636;
  --text:#ececf4; --text-dim:#9b9bb4; --text-faint:#6a6a85;
  --accent:#8b5cf6; --accent-hi:#a78bfa; --accent-soft:rgba(139,92,246,.14);
  --ok:#4ade80; --warn:#fbbf24; --err:#f87171;
  --r-sm:8px; --r-md:12px; --r-lg:18px; --r-xl:26px;
  --shadow:0 8px 30px rgba(0,0,0,.35);
  --ease:cubic-bezier(.2,.7,.2,1); --t-fast:140ms; --t:240ms;
  --font:"Geist",system-ui,sans-serif; --mono:"Geist Mono",ui-monospace,monospace;
}
```
- Type scale: 12 / 13 / 15 (body) / 17 / 22 / 32 / 56. Body line-height 1.65. Chat column max-width **740px**.
- Ambient effect: ONE slow radial-gradient glow behind the composer (CSS only, 20 s loop). Disabled under `prefers-reduced-motion`.
- Light theme: tokens swap via `[data-theme=light]`. Default follows the OS.
- Glass is allowed only on the composer and popovers (`backdrop-filter: blur(14px)`), never on every card.

## 3. Screens and components

### 3.1 Landing (single screen above the fold, then short sections)
- Hero: one headline, one sentence, one CTA ("Start a private chat"). Below it, a live **"Privacy receipt" demo** that animates a fake request: received → processed in RAM → answered → nothing kept.
- Sections: How it works (3 steps), "What we do and don't do" (honest two-column list, including the Tavily disclosure), footer.

### 3.2 App shell
- **Left rail** (collapsible, 280 px): New chat, in-memory chat list with a "cleared on refresh" note, settings, privacy status.
- **Top bar:** model badge (from `/health`), connection state, **Privacy receipt button**.
- **Conversation:** user and assistant messages, markdown rendered, code blocks with copy button, streaming caret.
- **Composer (glass):**
  - Auto-growing textarea, Enter sends, Shift+Enter newline.
  - Attach button opens a menu: Image, (later) PDF.
  - **Mode chips:** `Auto` (default) · `Search` · `Image` · `Doc` · `Slides`. Auto lets the backend router decide. Manual chips override it.
  - Stop button while streaming.

### 3.3 Message-level UI
- **Route pill** under each assistant message, from the `route` event: `Local answer` · `Searched the web` · `Image edit` · `Document` · `Slides`.
- **Status line** while working: "Searching the web…" → "Reading 5 sources…" → "Writing…" (from `status` events).
- **Sources** as compact chips with favicon-free domain labels. Clicking opens in a new tab with `rel="noopener noreferrer"`.
- **Artifact card** (`artifact` event): file icon, title, size, **Download** button, and a note "Generated in memory. Not saved on the server." Files arrive as base64 and download via a Blob URL.
- **Image result card:** before/after **comparison slider**, edit chips (Remove BG, Grayscale, Blur, Sharpen, Brightness, Contrast, Saturation, Rotate, Flip, Crop), Undo (in-memory stack), Download PNG.

### 3.4 Privacy receipt (popover)
Shows, per response: where it ran (local model name), whether search was used and the exact query sent to the search provider, bytes kept on server (0), time taken. This is the signature feature. Data comes from the final `done` event.

### 3.5 Other
- Command palette (Cmd/Ctrl+K): new chat, switch mode, clear all, toggle theme.
- Empty state: 4 suggestion chips that cover chat, search, image and doc.
- Toasts for errors, with Retry. A connection-lost banner when `/health` fails.

## 4. Non-functional requirements
- Lighthouse: Performance ≥ 90, Accessibility ≥ 95 (mobile profile).
- WCAG AA contrast, visible focus rings, full keyboard operation, `aria-live="polite"` on the streaming message, honour `prefers-reduced-motion`.
- Mobile first: composer sticky at the bottom with safe-area insets; rail becomes a drawer under 860 px.
- JS: ES modules in `frontend/js/` (`api.js`, `stream.js`, `state.js`, `render.js`, `components/*.js`). No global functions, no inline `onclick`.
- Render model output ONLY through `marked` + `DOMPurify`. Never use `innerHTML` with raw model text.
- Delete all legacy code: fake `generateAIResponse`, `handleSend`, duplicate edit paths.

## 5. API contract (v1)

Base: same origin (`/`). Nginx or FastAPI serves `frontend/`; API lives under `/api/v1`.

### `POST /api/v1/chat` → `text/event-stream`
Request:
```json
{ "message": "string (1..4000)",
  "history": [{"role":"user|assistant","content":"string"}],
  "mode": "auto|search|doc|slides",
  "stream": true }
```
`history` is sent by the client each time (max 12 turns) so the server stays stateless.

SSE events (`event:` name, JSON `data:`):
| event | data |
|---|---|
| `route` | `{"route":"chat\|search\|doc\|slides","reason":"short string"}` |
| `status` | `{"text":"Searching the web…"}` |
| `sources` | `{"items":[{"title","url","snippet"}],"query":"exact query sent to provider"}` |
| `token` | `{"text":"partial text"}` |
| `artifact` | `{"kind":"docx\|pptx","filename":"…","mime":"…","size":123,"data_b64":"…"}` |
| `done` | `{"model":"llama3.1:8b","route":"…","search_used":true,"elapsed_ms":2310,"retained_bytes":0}` |
| `error` | `{"message":"user-safe string"}` |

### `POST /api/v1/image` (multipart: `file`, `instruction`, optional `action`, `level`)
Returns JSON: `{"type":"analysis","text":"…"}` or `{"type":"image","action":"…","image_b64":"…","mime":"image/png"}`.
Explicit `action` wins; otherwise the router decides between analysis and an edit. Actions: `remove_bg, grayscale, blur, sharpen, brightness, contrast, saturation, rotate, flip_h, flip_v, crop, add_text, remove_text`.

### `GET /api/v1/health`
`{"status":"ok","ollama":true,"search":true,"text_model":"…","vision_model":"…"}`

### Errors
Always `{"error":{"code":"string","message":"user-safe"}}` with the proper HTTP status. Never echo user content or exception text.

## 6. Task breakdown for Antigravity (run in order)
1. **Scaffold:** create `frontend/` with the folder layout above, `tokens.css`, `base.css`, self-hosted fonts, vendor libs. Move nothing from the old files yet.
2. **App shell + composer + conversation** against a **mock SSE server** (`frontend/dev/mock.js`) that emits every event type in the contract.
3. **Message rendering:** markdown, code copy, route pill, status line, sources, streaming caret, stop button.
4. **Artifact and image cards:** comparison slider, edit chips, undo stack, download.
5. **Privacy receipt popover + command palette + toasts + connection banner.**
6. **Landing page** with the animated privacy receipt demo.
7. **Polish pass:** a11y audit, reduced motion, light theme, mobile drawer, Lighthouse run. Fix to targets in section 4.
8. **Swap mock for real backend** once the backend agent confirms the contract.

## 7. Definition of done
- No request leaves the origin except the search disclosure already shown to the user.
- Zero console errors; no inline handlers; no raw `innerHTML` of model text.
- Every contract event is handled, including `error`.
- Section 4 targets pass.

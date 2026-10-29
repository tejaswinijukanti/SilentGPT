/* ==========================================
   SilentGPT — app.js
   All animations, chat logic, canvas effects
   ========================================== */

"use strict";

/* ---- API CONFIG ---- */
// Use window.location.origin / relative paths without hardcoded local ports
const API_BASE = (typeof window !== "undefined" && window.location && window.location.origin && window.location.origin !== "null")
  ? window.location.origin
  : "";

/* ---- STATE ---- */
const state = {
  chatOpen: false,
  messages: [],
  pendingImage: null,
  pendingImageFile: null,
  isResponding: false,
  chatHistory: [],
  activeChatId: null,
};

/* ==========================================
   IMAGE GENERATION REQUEST DETECTION
   ========================================== */
function isImageGenerateRequest(text) {
  const t = (text || "").toLowerCase();
  return (
    /\b(generate|create|make|draw)\b/.test(t) &&
    /\b(image|picture|photo|illustration|invitation|poster)\b/.test(t)
  );
}

/* ==========================================
   DOCUMENT & PRESENTATION DETECTION / GENERATION
   ========================================== */
function detectFileRequest(message) {
  const text = (message || "").toLowerCase().trim();
  console.log("[SilentGPT] detectFileRequest:", text);

  const isPpt =
    /\b(presentation|slides|powerpoint|\bppt\b)\b/.test(text) &&
    /\b(make|create|generate|need|give|prepare|write)\b/.test(text);

  const isDoc =
    /\b(document|documentation|report|notes|\bdocx\b)\b/.test(text) &&
    /\b(make|create|generate|need|give|prepare|write)\b/.test(text);

  if (isPpt) {
    const topic = extractTopicFromMessage(text);
    console.log("[SilentGPT] PPT detected, topic:", topic);
    return { type: "presentation", topic };
  }
  if (isDoc) {
    const topic = extractTopicFromMessage(text);
    console.log("[SilentGPT] DOC detected, topic:", topic);
    return { type: "document", topic };
  }
  console.log("[SilentGPT] no file request");
  return null;
}

function extractTopicFromMessage(text) {
  return text
    .replace(/\b(make|create|generate|need|give|prepare|write|me|a|an|the|on|about|for|regarding|of|in|even|used|to|u)\b/gi, " ")
    .replace(/\b(presentation|slides|powerpoint|ppt|document|documentation|report|notes|docx)\b/gi, " ")
    .replace(/\s+/g, " ")
    .trim() || "General Topic";
}

async function handleFileGeneration(type, topic, instructions) {
  const typingId = showTyping();
  try {
    const endpoint = type === "document"
      ? `${API_BASE}/generate-document`
      : `${API_BASE}/generate-presentation`;

    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        topic: topic,
        instructions: instructions || topic
      })
    });

    removeTyping(typingId);

    if (!response.ok) {
      appendMessage({ role: "ai", text: "Could not generate the file. Try again." }, true);
      return;
    }

    const blob = await response.blob();
    let filename = type === "document" ? "SilentGPT_Document.docx" : "SilentGPT_Presentation.pptx";
    const cd = response.headers.get("Content-Disposition") || "";
    const match = cd.match(/filename="?([^"]+)"?/);
    if (match) filename = match[1];

    const url = URL.createObjectURL(blob);
    showDownloadMessage(type, topic, url, filename);
  } catch (e) {
    removeTyping(typingId);
    console.error(e);
    appendMessage({ role: "ai", text: "Error generating file." }, true);
  }
}

function showDownloadMessage(type, topic, downloadUrl, filename) {
  const chatBox = document.getElementById("chat-messages");
  if (!chatBox) return;

  const wrapper = document.createElement("div");
  wrapper.className = "message ai-message";

  const bubble = document.createElement("div");
  bubble.className = "message-bubble";
  bubble.style.padding = "14px";

  const label = type === "document" ? "Document" : "Presentation";
  bubble.innerHTML = `<p style="margin:0 0 10px 0">Your ${label} on <strong>${topic}</strong> is ready.</p>`;

  const a = document.createElement("a");
  a.href = downloadUrl;
  a.download = filename;
  a.textContent = `Download ${label}`;
  a.style.cssText = "display:inline-block;padding:8px 16px;border-radius:10px;background:rgba(139,92,246,0.35);color:#e9d5ff;text-decoration:none;border:1px solid rgba(167,139,250,0.5)";
  bubble.appendChild(a);

  wrapper.appendChild(bubble);
  chatBox.appendChild(wrapper);
  scrollToBottom();
}

/* ==========================================
   MATRIX RAIN CANVAS
   ========================================== */
(function initMatrix() {
  const canvas = document.getElementById("matrix-canvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  let cols = 0, drops = [];

  const CHARS = "01アイウエオカキクケコサシスセソタチツテトナニヌネノ";
  const FONT_SIZE = 13;
  const COLORS = ["rgba(168,85,247,", "rgba(99,102,241,", "rgba(232,121,249,"];

  function resize() {
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
    cols = Math.floor(canvas.width / FONT_SIZE);
    drops = Array.from({ length: cols }, () => Math.random() * -100);
  }

  function draw() {
    ctx.fillStyle = "rgba(5,5,8,0.05)";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.font = `${FONT_SIZE}px monospace`;
    for (let i = 0; i < cols; i++) {
      const char = CHARS[Math.floor(Math.random() * CHARS.length)];
      const colorBase = COLORS[i % COLORS.length];
      const alpha = Math.random() * 0.3 + 0.03;
      ctx.fillStyle = `${colorBase}${alpha})`;
      ctx.fillText(char, i * FONT_SIZE, drops[i] * FONT_SIZE);
      if (drops[i] * FONT_SIZE > canvas.height && Math.random() > 0.975) drops[i] = 0;
      drops[i]++;
    }
  }

  resize();
  window.addEventListener("resize", resize);
  setInterval(draw, 60);
})();

/* ==========================================
   FLUID WAVE CANVAS
   ========================================== */
(function initWave() {
  const canvas = document.getElementById("wave-canvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  let width, height, t = 0;
  let mouseX = 0.5, mouseY = 0.5;
  let targetMouseX = 0.5, targetMouseY = 0.5;

  function resize() {
    width = canvas.width = window.innerWidth;
    height = canvas.height = window.innerHeight;
  }

  document.addEventListener("mousemove", (e) => {
    targetMouseX = e.clientX / window.innerWidth;
    targetMouseY = e.clientY / window.innerHeight;
  });

  function drawOrb(cx, cy, r, r1, g1, b1, alpha) {
    const grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, r);
    grad.addColorStop(0, `rgba(${r1},${g1},${b1},${alpha})`);
    grad.addColorStop(0.5, `rgba(${r1},${g1},${b1},${alpha * 0.35})`);
    grad.addColorStop(1, `rgba(${r1},${g1},${b1},0)`);
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.fill();
  }

  function drawWave(yBase, amplitude, frequency, speed, r1, g1, b1, alpha, lineWidth) {
    ctx.beginPath();
    ctx.lineWidth = lineWidth;
    ctx.strokeStyle = `rgba(${r1},${g1},${b1},${alpha})`;
    for (let x = 0; x <= width; x += 2) {
      const xNorm = x / width;
      const y = yBase
        + Math.sin(xNorm * frequency * Math.PI + t * speed) * amplitude
        + Math.sin(xNorm * (frequency * 1.7) * Math.PI + t * (speed * 0.7) + 1) * (amplitude * 0.35)
        + Math.sin(xNorm * (frequency * 0.5) * Math.PI + t * (speed * 1.3) + 2.5) * (amplitude * 0.2)
        + (mouseY - 0.5) * amplitude * 0.4;
      if (x === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
  }

  function draw() {
    ctx.clearRect(0, 0, width, height);
    t += 0.007;
    mouseX += (targetMouseX - mouseX) * 0.04;
    mouseY += (targetMouseY - mouseY) * 0.04;

    const cx = width * (0.25 + mouseX * 0.5);
    const cy = height * (0.25 + mouseY * 0.5);
    drawOrb(cx, cy, width * 0.38, 168, 85, 247, 0.09);
    drawOrb(width * 0.72 + Math.sin(t * 0.4) * 40, height * 0.38 + Math.cos(t * 0.3) * 30, width * 0.3, 99, 102, 241, 0.07);
    drawOrb(width * 0.5 + Math.cos(t * 0.5) * 50, height * 0.6 + Math.sin(t * 0.35) * 25, width * 0.22, 232, 121, 249, 0.05);
    drawOrb(width * 0.15 + Math.sin(t * 0.6) * 30, height * 0.7, width * 0.18, 168, 85, 247, 0.04);

    const midY = height * 0.5;
    drawWave(midY,      60, 2.5, 0.65, 168, 85,  247, 0.13, 1.8);
    drawWave(midY + 15, 48, 3.2, 0.50, 99,  102, 241, 0.10, 1.3);
    drawWave(midY - 20, 70, 2.0, 0.85, 232, 121, 249, 0.08, 1.1);
    drawWave(midY + 35, 38, 4.0, 0.38, 168, 85,  247, 0.06, 0.9);
    drawWave(midY - 40, 30, 5.0, 0.28, 99,  102, 241, 0.05, 0.7);

    const gl = ctx.createRadialGradient(width / 2, midY, 0, width / 2, midY, Math.min(width, height) * 0.55);
    gl.addColorStop(0, "rgba(168,85,247,0.04)");
    gl.addColorStop(0.5, "rgba(99,102,241,0.02)");
    gl.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = gl;
    ctx.fillRect(0, 0, width, height);
  }

  resize();
  window.addEventListener("resize", resize);
  function loop() { draw(); requestAnimationFrame(loop); }
  loop();
})();

/* ==========================================
   NAVBAR
   ========================================== */
(function initNavbar() {
  const nav = document.getElementById("navbar");
  const hamburger = document.getElementById("nav-hamburger");
  const navLinks = document.getElementById("nav-links");

  window.addEventListener("scroll", () => {
    if (window.scrollY > 30) nav.classList.add("scrolled");
    else nav.classList.remove("scrolled");
  }, { passive: true });

  if (hamburger) {
    hamburger.addEventListener("click", () => {
      const isOpen = navLinks.classList.toggle("open");
      hamburger.setAttribute("aria-expanded", isOpen);
    });
  }

  navLinks && navLinks.querySelectorAll(".nav-link").forEach(link => {
    link.addEventListener("click", () => {
      navLinks.classList.remove("open");
      hamburger && hamburger.setAttribute("aria-expanded", "false");
    });
  });
})();

/* ==========================================
   SCROLL REVEAL
   ========================================== */
(function initScrollReveal() {
  const elements = document.querySelectorAll("[data-animate]");
  if (!elements.length) return;
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) { entry.target.classList.add("visible"); observer.unobserve(entry.target); }
    });
  }, { threshold: 0.12, rootMargin: "0px 0px -40px 0px" });
  elements.forEach(el => observer.observe(el));
})();

/* ==========================================
   CHAT HISTORY HELPERS
   ========================================== */
function genId() { return `chat_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`; }

function getConversationTitle(messages) {
  const firstUser = messages.find(m => m.role === "user");
  if (!firstUser || !firstUser.text) return "New conversation";
  const t = firstUser.text.trim();
  return t.length > 42 ? t.slice(0, 42) + "\u2026" : t;
}

function saveCurrentToHistory() {
  if (state.messages.length === 0) return;
  const title = getConversationTitle(state.messages);
  if (state.activeChatId) {
    const existing = state.chatHistory.find(c => c.id === state.activeChatId);
    if (existing) { existing.messages = [...state.messages]; existing.title = title; renderSidebarHistory(); return; }
  }
  const entry = { id: genId(), title, messages: [...state.messages], timestamp: Date.now() };
  state.chatHistory.unshift(entry);
  state.activeChatId = entry.id;
  renderSidebarHistory();
}

function renderSidebarHistory() {
  const container = document.getElementById("sidebar-history");
  if (!container) return;
  if (state.chatHistory.length === 0) {
    container.innerHTML = `<div class="sidebar-history-empty">No recent chats</div>`;
    return;
  }
  container.innerHTML = state.chatHistory.map(chat => `
    <div class="sidebar-history-item ${chat.id === state.activeChatId ? "active" : ""}"
         data-chat-id="${escAttr(chat.id)}"
         onclick="loadChat('${escAttr(chat.id)}')"
         title="${escAttr(chat.title)}">
      <svg class="history-icon" width="11" height="11" viewBox="0 0 24 24" fill="none">
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
      <span class="history-title">${escHtml(chat.title)}</span>
      <button class="history-delete-btn" onclick="deleteHistoryChat(event,'${escAttr(chat.id)}')" title="Delete" aria-label="Delete chat">
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none"><path d="M18 6L6 18M6 6l12 12" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/></svg>
      </button>
    </div>
  `).join("");
}

function loadChat(chatId) {
  saveCurrentToHistory();
  const chat = state.chatHistory.find(c => c.id === chatId);
  if (!chat) return;
  state.messages = [...chat.messages];
  state.activeChatId = chatId;
  state.pendingImage = null;
  const container = document.getElementById("chat-messages");
  if (!container) return;
  container.innerHTML = "";
  state.messages.forEach(msg => appendMessage(msg, false));
  scrollToBottom();
  document.querySelectorAll(".sidebar-history-item").forEach(el => {
    el.classList.toggle("active", el.dataset.chatId === chatId);
  });
}

function deleteHistoryChat(e, chatId) {
  e.stopPropagation();
  state.chatHistory = state.chatHistory.filter(c => c.id !== chatId);
  if (state.activeChatId === chatId) { state.messages = []; state.activeChatId = null; renderWelcome(); }
  renderSidebarHistory();
}

/* ==========================================
   CHAT OPEN / CLOSE / NEW
   ========================================== */
function openChat() {
  state.chatOpen = true;
  const section = document.getElementById("chat-section");
  document.body.classList.add("chat-lock");
  section.classList.remove("chat-hidden");
  section.classList.add("chat-visible");
  if (state.messages.length === 0) renderWelcome();
  setTimeout(() => { const input = document.getElementById("chat-input"); if (input) input.focus(); }, 400);
}

function closeChat() {
  saveCurrentToHistory();
  state.chatOpen = false;
  const section = document.getElementById("chat-section");
  document.body.classList.remove("chat-lock");
  section.classList.add("chat-hidden");
  section.classList.remove("chat-visible");
}

function newChat() {
  saveCurrentToHistory();
  state.messages = []; state.activeChatId = null; state.pendingImage = null;
  const previewContainer = document.getElementById("image-preview-container");
  if (previewContainer) previewContainer.innerHTML = "";
  renderWelcome();
  setTimeout(() => { const input = document.getElementById("chat-input"); if (input) input.focus(); }, 200);
}

function downloadCurrentChat() {
  const messages = state.messages || [];
  if (!messages.length) {
    alert("No messages to download");
    return;
  }

  let text = "SilentGPT Chat Export\n";
  text += "======================\n\n";

  messages.forEach((m) => {
    const role = m.role === "user" ? "You" : "SilentGPT";
    const content = m.text || m.image || "[image]";
    text += `${role}:\n${content}\n\n`;
  });

  text += "\n---\nZero Data Retention · Exported locally only\n";

  const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `SilentGPT_Chat_${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-")}.txt`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function clearChat() {
  // Clear ALL history and current chat
  state.chatHistory = [];
  state.messages = [];
  state.activeChatId = null;
  state.pendingImage = null;
  const previewContainer = document.getElementById("image-preview-container");
  if (previewContainer) previewContainer.innerHTML = "";
  renderSidebarHistory();
  renderWelcome();
}

/* ==========================================
   RENDER WELCOME
   ========================================== */
function renderWelcome() {
  const messagesEl = document.getElementById("chat-messages");
  if (!messagesEl) return;
  const suggestions = [
    "What happened in the news today?",
    "Explain quantum computing simply",
    "What are the latest AI developments?",
    "How does blockchain work?",
  ];
  messagesEl.innerHTML = `
    <div class="chat-welcome" id="chat-welcome">
      <div class="chat-welcome-orb">
        <div class="chat-welcome-orb-ring"></div>
        <div class="chat-welcome-orb-ring2"></div>
        <div class="chat-welcome-icon-inner">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none">
            <circle cx="12" cy="12" r="10" stroke="url(#wg)" stroke-width="1.4"/>
            <path d="M7.5 14 Q9.5 9 12 14 Q14.5 19 16.5 14" stroke="url(#wg)" stroke-width="2" fill="none" stroke-linecap="round"/>
            <defs><linearGradient id="wg" x1="0" y1="0" x2="24" y2="24" gradientUnits="userSpaceOnUse"><stop stop-color="#c084fc"/><stop offset="1" stop-color="#e879f9"/></linearGradient></defs>
          </svg>
        </div>
      </div>
      <h2 class="chat-welcome-title">How can I help you?</h2>
      <p class="chat-welcome-sub">Ask anything — I search the live web for answers and forget everything the moment I respond.</p>
      <div class="chat-welcome-suggestions">
        ${suggestions.map(s => `<button class="suggestion-chip" onclick="useSuggestion(this)">${escHtml(s)}</button>`).join("")}
      </div>
    </div>
  `;
}

function useSuggestion(btn) {
  const input = document.getElementById("chat-input");
  if (input) { input.value = btn.textContent; input.focus(); autoResize(input); }
}

/* ==========================================
   SEND MESSAGE — Connected to POST /chat
   ========================================== */
async function sendMessage() {
  // Block concurrent requests
  if (state.isResponding) return;

  const input = document.getElementById("chat-input");
  const sendBtn = document.getElementById("send-btn");
  const text = (input ? input.value.trim() : "");
  const image = state.pendingImage;
  let imageFile = state.pendingImageFile;
  if (!text && !image && !imageFile) return;

  // Reconstruct File object from base64 data URL if imageFile is missing
  if (!imageFile && image && typeof image === "string" && image.startsWith("data:")) {
    try {
      const arr = image.split(",");
      const mime = (arr[0].match(/:(.*?);/) || [])[1] || "image/png";
      const bstr = atob(arr[1]);
      let n = bstr.length;
      const u8arr = new Uint8Array(n);
      while (n--) {
        u8arr[n] = bstr.charCodeAt(n);
      }
      imageFile = new File([u8arr], "uploaded_image.png", { type: mime });
    } catch (e) {
      console.warn("Could not convert data URL to File:", e);
    }
  }

  // Clear input field and image preview
  if (input) { input.value = ""; autoResize(input); }
  state.pendingImage = null;
  state.pendingImageFile = null;
  const previewContainer = document.getElementById("image-preview-container");
  if (previewContainer) previewContainer.innerHTML = "";

  // Dismiss welcome screen
  const welcome = document.getElementById("chat-welcome");
  if (welcome) {
    welcome.style.opacity = "0";
    welcome.style.transform = "scale(0.95)";
    welcome.style.transition = "all 0.2s";
    setTimeout(() => welcome.remove(), 200);
  }

  // Append user message bubble
  const userMsg = { role: "user", text, image };
  state.messages.push(userMsg);
  appendMessage(userMsg, true);
  saveCurrentToHistory();

  // ===== IMAGE GENERATION (text only, no upload) =====
  if (!imageFile && !image && isImageGenerateRequest(text)) {
    const typingId = showTyping();
    state.isResponding = true;
    if (sendBtn) sendBtn.disabled = true;
    try {
      const res = await fetch(`${API_BASE}/generate-image`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: text, message: text }),
      });
      const data = await res.json();
      removeTyping(typingId);

      if (data.image && !data.error) {
        showEditedImage(data.image, data.action || "generate");
        state.pendingImage = data.image;
        try {
          const resBlob = await fetch(data.image);
          const blob = await resBlob.blob();
          state.pendingImageFile = new File([blob], "generated_image.png", { type: "image/png" });
        } catch (e) {}
        showImagePreview(data.image);
        const aiMsg = { role: "ai", text: `✅ Generated: ${data.response || "Done."}`, isHTML: false };
        state.messages.push(aiMsg);
        saveCurrentToHistory();
      } else {
        appendMessage({
          role: "ai",
          text: data.error || data.response || "Could not generate image.",
        }, true);
      }
    } catch (e) {
      removeTyping(typingId);
      console.error(e);
      appendMessage({ role: "ai", text: "Image generation failed." }, true);
    } finally {
      if (sendBtn) sendBtn.disabled = false;
      state.isResponding = false;
    }
    return; // critical — do not call /chat
  }
  // ===== END =====

  // File generation short-circuit (only when NO image is attached)
  if (!imageFile && !image) {
    const fileRequest = detectFileRequest(text);
    if (fileRequest) {
      await handleFileGeneration(fileRequest.type, fileRequest.topic, text);
      return;
    }
  }

  // Show thinking animation while waiting for backend
  const typingId = showTyping();
  state.isResponding = true;

  // Disable send button during request
  if (sendBtn) sendBtn.disabled = true;

  let aiResponse = "";

  try {
    if (imageFile) {
      // image present → ONLY /image + Gemini
      const formData = new FormData();
      formData.append("file", imageFile);
      formData.append("instruction", text || "Describe this image.");
      formData.append("message", text || "Describe this image.");

      const res = await fetch(`${API_BASE}/image`, {
        method: "POST",
        body: formData,
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Server error (${res.status})`);
      }
      const data = await res.json();

      if (data.type === "image" && data.image) {
        showEditedImage(data.image, "gemini");

        // Update state so follow-up edits use the new image
        state.pendingImage = data.image;
        try {
          const resBlob = await fetch(data.image);
          const blob = await resBlob.blob();
          state.pendingImageFile = new File([blob], "edited_gemini.png", { type: "image/png" });
        } catch (e) {
          console.warn("Could not sync pendingImageFile:", e);
        }
        showImagePreview(data.image);

        const aiEditMsg = { role: "ai", text: `✅ Applied: ${data.response || "Done."}`, isHTML: false };
        state.messages.push(aiEditMsg);
        saveCurrentToHistory();
        removeTyping(typingId);
        if (sendBtn) sendBtn.disabled = false;
        state.isResponding = false;
        return;
      } else {
        removeTyping(typingId);
        if (sendBtn) sendBtn.disabled = false;
        state.isResponding = false;
        const replyText = cleanAIReply(data.response || "No result");
        const aiMsg = { role: "ai", text: replyText };
        state.messages.push(aiMsg);
        appendMessage(aiMsg, true);
        saveCurrentToHistory();
        return;
      }

    } else {
      // --- Text: POST ${API_BASE}/chat (JSON) ---
      const res = await fetch(`${API_BASE}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text }),
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Server error (${res.status})`);
      }
      const data = await res.json();
      aiResponse = data.response || "No response returned.";

      // Append web sources if search was configured and returned results
      if (data.sources && data.sources.length > 0) {
        const srcLines = data.sources
          .map((s, i) => `${i + 1}. ${s.title} — ${s.url}`)
          .join("\n");
        aiResponse += `\n\nSources:\n${srcLines}`;
      }
    }

  } catch (err) {
    // Show error message inline in the chat
    console.error("SilentGPT backend error:", err.message);
    aiResponse = `Could not reach the backend.\n${err.message}\n\nMake sure the server is running:\n  uvicorn main:app --reload`;

  } finally {
    // Always remove the thinking animation and re-enable input
    removeTyping(typingId);
    if (sendBtn) sendBtn.disabled = false;
  }

  // Append AI reply bubble
  aiResponse = cleanAIReply(aiResponse);
  const aiMsg = { role: "ai", text: aiResponse };
  state.messages.push(aiMsg);
  appendMessage(aiMsg, true);
  saveCurrentToHistory();

  state.isResponding = false;
  scrollToBottom();
}

/* ==========================================
   MESSAGE RENDERING
   ========================================== */
function appendMessage(msg, animate) {
  const container = document.getElementById("chat-messages");
  if (!container) return;

  const time = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const isUser = msg.role === "user";
  const el = document.createElement("div");
  el.className = `message ${isUser ? "user" : "ai"}`;
  if (!animate) el.style.animation = "none";

  if (isUser) {
    el.innerHTML = `
      <div class="message-row">
        ${msg.image ? `<img src="${escAttr(msg.image)}" class="message-image" alt="Uploaded image"/>` : ""}
        ${msg.text ? `<div class="message-bubble">${escHtml(msg.text)}</div>` : ""}
      </div>
      <span class="message-time">${time}</span>
    `;
    container.appendChild(el);
    scrollToBottom();
  } else {
    const avatarUid = `av-${Date.now()}`;
    el.innerHTML = `
      <div class="message-row">
        ${animate ? makeAvatarHTML('done', avatarUid) : makeAvatarHTML('default', avatarUid)}
        <div class="message-bubble" id="ai-b-${Date.now()}"></div>
      </div>
      <span class="message-time">${time}</span>
    `;
    container.appendChild(el);
    scrollToBottom();
    const bubble = el.querySelector(".message-bubble");
    if (bubble) {
      if (msg.isHTML) {
        bubble.innerHTML = msg.text;
      } else if (animate) {
        typewriterEffect(bubble, msg.text);
      } else {
        bubble.innerHTML = escHtml(msg.text);
      }
    }
    // Transition: done smile → default logo after 1.7s
    if (animate) {
      setTimeout(() => {
        const av = document.getElementById(avatarUid);
        if (!av) return;
        av.style.opacity = '0';
        av.style.transform = 'scale(0.7)';
        av.style.transition = 'opacity 0.22s ease, transform 0.22s ease';
        setTimeout(() => {
          const av2 = document.getElementById(avatarUid);
          if (!av2) return;
          av2.outerHTML = makeAvatarHTML('default', avatarUid + '-d');
          const av3 = document.getElementById(avatarUid + '-d');
          if (av3) av3.classList.add('av-fade-in');
        }, 220);
      }, 1700);
    }
    return;
  }
}

function makeAvatarHTML(avatarState, uid) {
  if (avatarState === 'thinking') {
    return `<div class="ai-avatar av-thinking" id="${uid}">
      <svg class="av-spin-arc" width="16" height="16" viewBox="0 0 32 32" fill="none">
        <circle cx="16" cy="16" r="13" stroke="rgba(168,85,247,0.25)" stroke-width="2.5"/>
        <path d="M16 3 A13 13 0 0 1 29 16" stroke="#c084fc" stroke-width="2.5" stroke-linecap="round"/>
      </svg>
    </div>`;
  }
  if (avatarState === 'done') {
    return `<div class="ai-avatar av-done" id="${uid}">
      <svg width="18" height="18" viewBox="0 0 32 32" fill="none">
        <circle cx="16" cy="16" r="13" stroke="#c084fc" stroke-width="2"/>
        <circle class="av-eye" cx="11.5" cy="13" r="1.8" fill="#c084fc"/>
        <circle class="av-eye av-eye-r" cx="20.5" cy="13" r="1.8" fill="#c084fc"/>
        <path class="av-smile" d="M10 18 Q16 24.5 22 18" stroke="#e879f9" stroke-width="2.2" stroke-linecap="round" fill="none"/>
      </svg>
    </div>`;
  }
  // default
  return `<div class="ai-avatar" id="${uid}">
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
      <circle cx="12" cy="12" r="10" stroke="#fff" stroke-width="1.5"/>
      <path d="M8 14 Q10 10 12 14 Q14 18 16 14" stroke="#fff" stroke-width="1.8" fill="none" stroke-linecap="round"/>
    </svg>
  </div>`;
}

function typewriterEffect(el, text, speed) {
  speed = speed || 16;
  const words = text.split(" ");
  let i = 0;
  el.textContent = "";
  function writeNext() {
    if (i < words.length) {
      el.textContent += (i === 0 ? "" : " ") + words[i];
      i++;
      scrollToBottom();
      setTimeout(writeNext, speed + Math.random() * 10);
    }
  }
  writeNext();
}

let thinkingTimer = null;
let thinkingStart = 0;

function showTyping() {
  const container = document.getElementById("chat-messages");
  if (!container) return null;
  const id = `typing-${Date.now()}`;
  thinkingStart = Date.now();

  const el = document.createElement("div");
  el.className = "message ai";
  el.id = id;
  el.innerHTML = `
    <div class="message-row">
      ${makeAvatarHTML('thinking', `av-typing-${Date.now()}`)}
      <div class="thinking-status">
        <div class="thinking-dot"></div>
        <span class="thinking-text">Working… 0.0s</span>
      </div>
    </div>
  `;
  container.appendChild(el);
  scrollToBottom();

  if (thinkingTimer) clearInterval(thinkingTimer);
  thinkingTimer = setInterval(() => {
    const sec = ((Date.now() - thinkingStart) / 1000).toFixed(1);
    const label = el.querySelector(".thinking-text");
    if (label) label.textContent = `Working… ${sec}s`;
  }, 100);

  return id;
}

function removeTyping(id) {
  if (thinkingTimer) {
    clearInterval(thinkingTimer);
    thinkingTimer = null;
  }
  if (!id) return;
  const el = document.getElementById(id);
  if (el) el.remove();
}
function scrollToBottom() { const c = document.getElementById("chat-messages"); if (c) c.scrollTop = c.scrollHeight; }

/* ==========================================
   CLEAN & AI RESPONSES
   ========================================== */
function cleanAIReply(text) {
  if (!text) return "";
  return text
    .replace(/\n*🔒\s*Your query has been permanently deleted from our systems\.\s*$/i, "")
    .replace(/\n*🔒\s*Image has been permanently deleted from our systems\.\s*$/i, "")
    .replace(/\n*🔒\s*Zero data retention active\..*$/i, "")
    .replace(/\n*🔒\s*Private mode:.*$/i, "")
    .replace(/\n*🔒\s*SilentGPT guarantee:.*$/i, "")
    .trim();
}

function generateAIResponse(text, image) {
  if (image && !text) {
    return "I can see the image you've uploaded! I've analyzed its contents.";
  }
  const responses = [
    `Great question! I've searched across multiple live web sources to find the most current answer.\n\nBased on the latest information: "${text.slice(0,30)}..." has rich context. Real-time data suggests significant developments in the last 24–48 hours. I've cross-referenced multiple high-authority sources for this synthesized answer.`,
    `I found several relevant sources on this topic.\n\nIn short: the latest on "${text.slice(0,40)}..." points to fascinating insights. Multiple trusted sources confirm the core facts, with noteworthy recent updates.\n\nFor deeper exploration, just ask!`,
    `Searching the live web now... ✓\n\nHere's what I found about "${text.slice(0,35)}":\n\nThe current consensus is clear and well-supported. There's been notable expert discussion, and the latest data points to important conclusions.\n\nWant me to dive deeper?`,
    `Based on my real-time internet search:\n\nYour query touches on a timely subject. Here's the synthesized answer from the most authoritative sources:\n\nKey points are well-documented by multiple independent sources. Recent developments have added new dimensions that reshape expert understanding.`,
  ];
  return responses[Math.floor(Math.random() * responses.length)];
}



/* ==========================================
   DETECT EDIT ACTION (mirrors backend logic)
   ========================================== */
/**
 * Parse a natural-language instruction and return the matching
 * SUPPORTED_ACTIONS key, or null if no action is recognised.
 * Mirrors image_handler.detect_edit_action() in the Python backend.
 *
 * @param {string} text
 * @returns {string|null}
 */
function detect_edit_action(text) {
  if (!text) return null;
  const t = text.toLowerCase().trim();

  if (t.includes("remove background") || t.includes("remove bg") || t.includes("background remove"))
    return "remove_bg";
  if (t.includes("grayscale") || t.includes("black and white") || t.includes("b&w"))
    return "grayscale";
  if (t.includes("blur"))
    return "blur";
  if (t.includes("sharpen") || t.includes("sharp"))
    return "sharpen";
  if (t.includes("brightness") || t.includes("brighter") || t.includes("increase brightness"))
    return "brightness";

  return null;
}

/* ==========================================
   IMAGE UPLOAD
   ========================================== */
(function initImageUpload() {
  const input = document.getElementById("image-upload-input");
  if (!input) return;
  input.addEventListener("change", (e) => {
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    state.pendingImageFile = file;
    const reader = new FileReader();
    reader.onload = (ev) => { state.pendingImage = ev.target.result; showImagePreview(ev.target.result); };
    reader.readAsDataURL(file);
    e.target.value = "";
  });
})();

function showImagePreview(src) {
  const container = document.getElementById("image-preview-container");
  if (!container) return;
  container.innerHTML = `
    <div style="display:flex; flex-direction:column; gap:6px; width:100%;">
      <div class="image-preview-item">
        <img src="${escAttr(src)}" alt="Preview"/>
        <button class="image-preview-remove" onclick="removeImagePreview()" aria-label="Remove image">&times;</button>
      </div>
      <div class="image-edit-options">
        <button class="edit-btn" type="button" onclick="editImage('remove_bg')">Remove BG</button>
        <button class="edit-btn" type="button" onclick="editImage('grayscale')">Grayscale</button>
        <button class="edit-btn" type="button" onclick="editImage('blur')">Blur</button>
        <button class="edit-btn" type="button" onclick="editImage('sharpen')">Sharpen</button>
        <button class="edit-btn" type="button" onclick="editImage('brightness')">Brightness</button>
      </div>
    </div>
  `;
}

function removeImagePreview() {
  state.pendingImage = null;
  state.pendingImageFile = null;
  const container = document.getElementById("image-preview-container");
  if (container) container.innerHTML = "";
}

async function editImage(action) {
  if (!state.pendingImageFile) {
    alert("Please upload an image first.");
    return;
  }

  const formData = new FormData();
  formData.append("file", state.pendingImageFile);
  formData.append("action", action);

  let typingId = null;

  try {
    // Show typing animation
    typingId = showTyping();

    const response = await fetch(`${API_BASE}/edit-image`, {
      method: "POST",
      body: formData,
    });

    const data = await response.json();
    if (typingId) removeTyping(typingId);

    if (data.success) {
      // Update in-memory state so subsequent edits / sends use the edited image
      state.pendingImage = data.image;
      const resBlob = await fetch(data.image);
      const blob = await resBlob.blob();
      state.pendingImageFile = new File([blob], `edited_${action}.png`, { type: "image/png" });

      // Create image + download button and insert into chat
      const chatBox = document.getElementById("chat-messages");

      const wrapper = document.createElement("div");
      wrapper.className = "message ai-message";
      wrapper.style.marginTop = "10px";

      const bubble = document.createElement("div");
      bubble.className = "message-bubble";
      bubble.style.padding = "10px";

      // Edited Image
      const img = document.createElement("img");
      img.src = data.image;
      img.style.maxWidth = "280px";
      img.style.borderRadius = "12px";
      img.style.display = "block";
      img.style.marginBottom = "8px";

      // Download Button
      const downloadBtn = document.createElement("a");
      downloadBtn.href = data.image;
      downloadBtn.download = `silentgpt-edited-${action}.png`;
      downloadBtn.textContent = "Download Image";
      downloadBtn.style.display = "inline-block";
      downloadBtn.style.marginTop = "6px";
      downloadBtn.style.padding = "6px 12px";
      downloadBtn.style.borderRadius = "8px";
      downloadBtn.style.background = "rgba(139, 92, 246, 0.25)";
      downloadBtn.style.color = "#e9d5ff";
      downloadBtn.style.fontSize = "13px";
      downloadBtn.style.textDecoration = "none";
      downloadBtn.style.border = "1px solid rgba(167, 139, 250, 0.4)";

      bubble.appendChild(img);
      bubble.appendChild(downloadBtn);
      wrapper.appendChild(bubble);
      chatBox.appendChild(wrapper);

      // Scroll to bottom
      chatBox.scrollTop = chatBox.scrollHeight;

      // Refresh the preview thumbnail with the new image
      showImagePreview(data.image);
    } else {
      appendMessage({ role: "ai", text: "Failed to edit the image." }, true);
    }

  } catch (error) {
    if (typingId) removeTyping(typingId);
    console.error(error);
    appendMessage({ role: "ai", text: "Error while editing the image." }, true);
  }
}
/* ==========================================
   TEXTAREA AUTO-RESIZE
   ========================================== */
(function initTextarea() {
  const textarea = document.getElementById("chat-input");
  if (!textarea) return;
  textarea.addEventListener("input", () => autoResize(textarea));
  textarea.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  });
  textarea.addEventListener("paste", (e) => {
    const items = (e.clipboardData || e.originalEvent?.clipboardData)?.items;
    if (!items) return;
    for (const item of items) {
      if (item.type.indexOf("image") !== -1) {
        const file = item.getAsFile();
        if (file) {
          state.pendingImageFile = file;
          const reader = new FileReader();
          reader.onload = (ev) => {
            state.pendingImage = ev.target.result;
            showImagePreview(ev.target.result);
          };
          reader.readAsDataURL(file);
          break;
        }
      }
    }
  });
})();

function autoResize(el) { el.style.height = "auto"; el.style.height = Math.min(el.scrollHeight, 160) + "px"; }

/* ==========================================
   UTILITIES
   ========================================== */
function sleep(ms) { return new Promise(res => setTimeout(res, ms)); }

function escHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#039;").replace(/\n/g, "<br>");
}

function escAttr(str) { return String(str).replace(/"/g, "&quot;").replace(/'/g, "&#039;"); }

/* ==========================================
   CARD PARALLAX
   ========================================== */
(function initCardParallax() {
  const cards = document.querySelectorAll(".feature-card, .step-card");
  cards.forEach(card => {
    card.addEventListener("mousemove", (e) => {
      const rect = card.getBoundingClientRect();
      const x = (e.clientX - rect.left) / rect.width - 0.5;
      const y = (e.clientY - rect.top) / rect.height - 0.5;
      card.style.transform = `translateY(-6px) rotateX(${-y * 5}deg) rotateY(${x * 5}deg)`;
    });
    card.addEventListener("mouseleave", () => { card.style.transform = ""; });
  });
})();

/* ==========================================
   KEYBOARD SHORTCUT
   ========================================== */
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && state.chatOpen) closeChat(); });

/* ==========================================
   BACKEND HEALTH CHECK
   ========================================== */
async function checkBackendHealth() {
  try {
    const res = await fetch(`${API_BASE}/health`);
    if (res.ok) {
      const data = await res.json();
      console.log("SilentGPT backend status:", data);
      if (data.ollama_connected) {
        const statuses = document.querySelectorAll(".sidebar-status");
        statuses.forEach(s => {
          s.innerHTML = `<span class="sidebar-status-dot" style="background:#4ade80;box-shadow:0 0 8px #4ade80;" aria-hidden="true"></span><svg width="12" height="12" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 2L8 6H4v4l-2 2 2 2v4h4l4 4 4-4h4v-4l2-2-2-2V6h-4L12 2Z" stroke="#4ade80" stroke-width="2" stroke-linejoin="round"/></svg> Ollama AI Ready`;
        });
      }
    }
  } catch (e) {
    console.log("SilentGPT running in standalone/offline mode.");
  }
}

/* ==========================================
   HANDLE SEND (natural-language unified handler)
   ========================================== */
/**
 * Unified send handler used as an alternative entry point to sendMessage().
 * Routes image + text to /edit-image-natural, plain text to /chat,
 * and branches the rendered response on data.type ("image" vs "text").
 */
async function handleSend() {
  const userInput = document.getElementById("userInput")
    ? document.getElementById("userInput").value.trim()
    : (document.getElementById("chat-input") ? document.getElementById("chat-input").value.trim() : "");

  if (!userInput && !state.pendingImageFile) return;

  // Show user message bubble
  if (userInput) {
    appendMessage({ role: "user", text: userInput }, true);
  }

  // Clear input
  const inputEl = document.getElementById("userInput") || document.getElementById("chat-input");
  if (inputEl) { inputEl.value = ""; autoResize && autoResize(inputEl); }

  // Dismiss welcome screen
  const welcome = document.getElementById("chat-welcome");
  if (welcome) {
    welcome.style.opacity = "0";
    welcome.style.transform = "scale(0.95)";
    welcome.style.transition = "all 0.2s";
    setTimeout(() => welcome.remove(), 200);
  }

  // Image generation request
  if (!state.pendingImageFile && !state.pendingImage && isImageGenerateRequest(userInput)) {
    const typingId = showTyping();
    state.isResponding = true;
    if (sendBtn) sendBtn.disabled = true;
    try {
      const res = await fetch(`${API_BASE}/generate-image`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: userInput }),
      });
      const data = await res.json();
      removeTyping(typingId);
      if (data.image && !data.error) {
        showEditedImage(data.image, data.action || "generate");
        state.pendingImage = data.image;
        try {
          const resBlob = await fetch(data.image);
          const blob = await resBlob.blob();
          state.pendingImageFile = new File([blob], "generated_image.png", { type: "image/png" });
        } catch (e) {}
        showImagePreview(data.image);
        const aiMsg = { role: "ai", text: `✅ Generated: ${data.response || "Done."}`, isHTML: false };
        state.messages.push(aiMsg);
        saveCurrentToHistory();
      } else {
        appendMessage({ role: "ai", text: data.error || data.response || "Failed" }, true);
      }
    } catch (e) {
      removeTyping(typingId);
      appendMessage({ role: "ai", text: "Image generation error." }, true);
    } finally {
      if (sendBtn) sendBtn.disabled = false;
      state.isResponding = false;
    }
    return;
  }

  // Document / Presentation request (only when no image attached)
  if (!state.pendingImageFile && !state.pendingImage) {
    const fileRequest = detectFileRequest(userInput);
    if (fileRequest) {
      await handleFileGeneration(fileRequest.type, fileRequest.topic, userInput);
      return; // do not fall through to /chat
    }
  }

  let typingId = showTyping();
  state.isResponding = true;
  const sendBtn = document.getElementById("send-btn");
  if (sendBtn) sendBtn.disabled = true;

  try {
    let response, data;

    if (state.pendingImageFile) {
      // image present → ONLY /image + Gemini
      const formData = new FormData();
      formData.append("file", state.pendingImageFile);
      formData.append("instruction", userInput || "Describe this image.");
      formData.append("message", userInput || "Describe this image.");

      response = await fetch(`${API_BASE}/image`, {
        method: "POST",
        body: formData,
      });
    } else {
      // Plain text → /chat
      response = await fetch(`${API_BASE}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: userInput }),
      });
    }

    data = await response.json();
    removeTyping(typingId);

    if (data.type === "image" && data.image) {
      showEditedImage(data.image, "gemini");

      // Keep state in sync so follow-up edits chain
      state.pendingImage = data.image;
      try {
        const resBlob = await fetch(data.image);
        const blob = await resBlob.blob();
        state.pendingImageFile = new File([blob], "edited_gemini.png", { type: "image/png" });
      } catch (e) {
        console.warn("Could not sync pendingImageFile:", e);
      }
      showImagePreview(data.image);

      const aiMsg = { role: "ai", text: `✅ Applied: ${data.response || "Done."}`, isHTML: false };
      state.messages.push(aiMsg);
      saveCurrentToHistory();
    } else {
      const replyText = cleanAIReply(data.response || "No result");
      const aiMsg = { role: "ai", text: replyText };
      state.messages.push(aiMsg);
      appendMessage(aiMsg, true);
      saveCurrentToHistory();
    }

  } catch (error) {
    removeTyping(typingId);
    console.error("handleSend error:", error);
    appendMessage({ role: "ai", text: "Something went wrong. Please try again." }, true);
  } finally {
    if (sendBtn) sendBtn.disabled = false;
    state.isResponding = false;
    scrollToBottom();
  }
}

/* ==========================================
   SHOW EDITED IMAGE (inline chat bubble)
   ========================================== */
/**
 * Render an edited image inside the chat as an AI message bubble,
 * complete with a styled download link.
 *
 * @param {string} base64Image - data:image/png;base64,… URL
 * @param {string} action      - SUPPORTED_ACTIONS key, e.g. "grayscale"
 */
function showEditedImage(base64Image, action) {
  const chatBox = document.getElementById("chat-messages");
  if (!chatBox) return;

  const wrapper = document.createElement("div");
  wrapper.className = "message ai-message";
  wrapper.style.marginTop = "10px";

  const bubble = document.createElement("div");
  bubble.className = "message-bubble";
  bubble.style.padding = "10px";

  const img = document.createElement("img");
  img.src = base64Image;
  img.style.maxWidth = "300px";
  img.style.borderRadius = "12px";
  img.style.display = "block";
  img.style.marginBottom = "8px";

  const downloadBtn = document.createElement("a");
  downloadBtn.href = base64Image;
  downloadBtn.download = `silentgpt-${action}.png`;
  downloadBtn.textContent = "Download";
  downloadBtn.style.cssText = `
    display: inline-block;
    margin-top: 6px;
    padding: 6px 14px;
    border-radius: 8px;
    background: rgba(139, 92, 246, 0.25);
    color: #e9d5ff;
    font-size: 13px;
    text-decoration: none;
    border: 1px solid rgba(167, 139, 250, 0.4);
  `;

  bubble.appendChild(img);
  bubble.appendChild(downloadBtn);
  wrapper.appendChild(bubble);
  chatBox.appendChild(wrapper);

  chatBox.scrollTop = chatBox.scrollHeight;
}

/* ==========================================
   INIT
   ========================================== */
renderSidebarHistory();
checkBackendHealth();

/* ==========================================
   CHATGPT-STYLE DRAG & DROP
   ========================================== */
(function initChatDrop() {
  const panel = document.getElementById("chat-panel") ||
                document.getElementById("chat-section") ||
                document.getElementById("chat-messages")?.parentElement;
  const overlay = document.getElementById("drop-overlay");
  if (!panel || !overlay) return;

  let dragDepth = 0;

  panel.addEventListener("dragenter", (e) => {
    e.preventDefault();
    dragDepth++;
    overlay.classList.add("active");
  });

  panel.addEventListener("dragover", (e) => {
    e.preventDefault();
  });

  panel.addEventListener("dragleave", (e) => {
    e.preventDefault();
    dragDepth = Math.max(0, dragDepth - 1);
    if (dragDepth === 0) overlay.classList.remove("active");
  });

  panel.addEventListener("drop", (e) => {
    e.preventDefault();
    dragDepth = 0;
    overlay.classList.remove("active");

    const file = e.dataTransfer?.files?.[0];
    if (!file || !file.type.startsWith("image/")) return;

    state.pendingImageFile = file;
    const reader = new FileReader();
    reader.onload = (ev) => {
      state.pendingImage = ev.target.result;
      if (typeof showImagePreview === "function") {
        showImagePreview(ev.target.result);
      }
    };
    reader.readAsDataURL(file);
  });
})();

/* ==========================================
   VOICE INPUT (Speech-to-Text)
   ========================================== */
let recognition = null;
let isListening = false;

function initVoice() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) {
    console.warn("Speech recognition not supported in this browser");
    return;
  }

  recognition = new SR();
  recognition.lang = "en-IN";
  recognition.interimResults = true;
  recognition.continuous = false;

  recognition.onstart = () => {
    isListening = true;
    const btn = document.getElementById("voice-btn");
    if (btn) btn.classList.add("listening");
  };

  recognition.onend = () => {
    isListening = false;
    const btn = document.getElementById("voice-btn");
    if (btn) btn.classList.remove("listening");
  };

  recognition.onerror = (e) => {
    console.error("Voice error:", e.error);
    isListening = false;
    const btn = document.getElementById("voice-btn");
    if (btn) btn.classList.remove("listening");
  };

  recognition.onresult = (event) => {
    let transcript = "";
    for (let i = event.resultIndex; i < event.results.length; i++) {
      transcript += event.results[i][0].transcript;
    }
    const input = document.getElementById("chat-input");
    if (input) {
      input.value = transcript.trim();
      if (typeof autoResize === "function") autoResize(input);
    }
    // Auto-send when final result arrives
    // if (event.results[event.results.length - 1].isFinal) sendMessage();
  };
}

function toggleVoice() {
  if (!recognition) {
    alert("Voice input not supported. Please use Chrome or Edge.");
    return;
  }
  if (isListening) {
    recognition.stop();
  } else {
    recognition.start();
  }
}

document.addEventListener("DOMContentLoaded", () => {
  initVoice();
  document.getElementById("voice-btn")?.addEventListener("click", toggleVoice);
});

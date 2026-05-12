# HERMES Voice Assistant — Progress Log

## Project Overview
A JARVIS-inspired voice assistant with animated web UI, British TTS, wake word detection, and LLM-powered responses. Built to enhance Hermes (the CLI agent) with voice + visual capabilities.

**Location:** `~/.hermes/hermes-voice/`  
**Inspired by:** [Mark-X.1 / Mark XXXIX-OR](https://github.com/FatihMakes/Mark-XXXIX-OR) by FatihMakes  
**Video Reference:** https://www.youtube.com/watch?v=ldvDNzwnM8k

---

## Session 1 — May 12, 2026

### Research & Analysis
- Deep-dived the Mark-X.1 repo (`/Users/cklein/Documents/GitHub/Mark-X.1`)
- Reviewed YouTube video for Mark XXXIX-OR features
- Catalogued all features: animated face UI, Vosk STT, Edge TTS, intent routing, persistent memory, desktop automation, multi-step conversations, OpenRouter LLM routing
- Compared against Hermes's existing capabilities
- Identified top 3 features to build: Voice Input Daemon, JARVIS-style Web UI, Auto-Voice Replies

### Environment Setup
- Python 3.13.12 (Homebrew) selected as runtime
- Created venv at `~/.hermes/hermes-voice/venv`
- Installed dependencies:
  - `edge-tts` 7.2.8 — Microsoft Edge neural TTS
  - `openai-whisper` 20250625 — OpenAI Whisper for local STT
  - `websockets` 16.0 — real-time client-server comms
  - `aiohttp` 3.13.5 — async HTTP for OpenRouter API
  - `sounddevice` + `soundfile` + `numpy` — audio I/O
  - `torch` 2.11.0 — Whisper backend

### British Voice Selected
- Tested Edge TTS voices: `en-GB-RyanNeural` (male, British) ✅
- Also available: ThomasNeural, LibbyNeural, MaisieNeural, SoniaNeural
- Confirmed audio generation works (23KB test file played successfully)

### Backend Server Built (`server.py`)
- WebSocket server on `ws://127.0.0.1:8765`
- HTTP server on `http://127.0.0.1:8766` (serves web UI)
- **Wake word detection:** "Hermes" + common misheard variants
- **Whisper STT:** base model, local/offline transcription
- **Edge TTS:** British voice (en-GB-RyanNeural), streamed to client
- **LLM integration:** OpenRouter API → Claude Sonnet 4
- **Persona:** British JARVIS — dry wit, concise, sardonic
- **Conversation history:** Last 10 exchanges maintained
- **Hybrid input:** Voice (via mic) or keyboard text commands

### Web UI Built (`ui/index.html`)
- **Animated cyan orb** with 3 orbital rings (rotating, different speeds)
- **Orb states:**
  - Idle: gentle breathing animation (scale 1.0–1.03)
  - Speaking: intense pulse (scale 1.02–1.08) + bright cyan glow
  - Listening: orange glow + medium pulse (scale 1.0–1.05)
- **Scan-line overlay** — subtle CRT effect
- **Corner decorations** — HUD-style bracket corners
- **Typewriter text effect** — 12ms per character
- **Audio waveform visualizer** — frequency bars during recording
- **Chat log** — scrollable, fade-in entries, color-coded (orange=user, cyan=Hermes)
- **Input bar** — text field + MIC button + SEND button
- **Fonts:** Orbitron (headers), Rajdhani (body)
- **Color scheme:** Cyan (#00f0ff) on dark (#0a0a0f)

### Launcher Script (`start.sh`)
- Auto-activates venv
- Checks for `OPENROUTER_API_KEY` (env var or `.env` file)
- Interactive prompt if key missing

### v2 Performance & Audio Fix
- **Bug: Major delay** — LLM (1.8s) + TTS (1.8s) ran sequentially before showing text
  - Fix: Text response sent to UI IMMEDIATELY, TTS generates after
  - User sees the reply instantly while audio is being prepared
- **Bug: Audio cutoff** — last sentence cut off mid-playback
  - Root cause: Audio sent in 32KB chunks, browser tried to play partial MP3
  - Fix: Server now generates COMPLETE audio blob, sends as single binary message
  - UI creates proper Audio element with onended handler — no more cutoff
- **Optimisations:**
  - Reusable aiohttp session (no TCP reconnect per request)
  - Whisper transcription moved to thread pool executor (non-blocking event loop)
  - TTS rate bumped to +5% for snappier speech
  - Proper promise-based audio playback with error recovery

### UI State Machine + Persona Fix
- **Bug: Orb not changing states** — only had idle/speaking/listening, transitions weren't wired
  - Added **thinking state** (purple glow, subtle wobble rotation) — triggers on transcription + processing
  - Added **"PREPARING VOICE..."** status between text response and TTS
  - Proper state flow: Idle → Listening (orange) → Thinking (purple) → Speaking (cyan pulse) → Idle
  - All states properly clean up other states on transition
- **Bug: LLM doing roleplay** — outputting `*adjusts digital display*` cringe
  - Updated system prompt: "Never use asterisk actions. Write only spoken words."
  - Responses are TTS-friendly now — no narrated actions

### v3 Full Tool Access + Persona Fix
- **Major: Voice assistant now executes real tools** — not just a chatbot anymore
  - LLM classifies intent → routes to tool → executes locally → formats response
  - Two-stage LLM: classifier (picks tool + params) → executor (runs it) → formatter (spoken response)
- **Tools wired up:**
  - `email_list` — himalaya envelope list
  - `email_send` — himalaya message send (with proper template format)
  - `email_search` — himalaya envelope list with query
  - `email_read` — himalaya message read by ID
  - `calendar_today` — acal events list (today's date range)
  - `calendar_list` — acal events list (N days ahead)
  - `reminder_list` — remindctl list
  - `reminder_add` — remindctl add with list
  - `web_search` — DuckDuckGo via curl
  - `terminal` — shell commands with safety blocklist
  - `chat` — conversational fallback
- **Persona fix:** Carolyn is a woman — never "sir", use "Carolyn", "ma'am", or "Ms Klein"
- **Classifier prompt includes user context:** email addresses, explicit instructions to USE tools

### UI Orb Animation Fix + Dashboard Tools
- **Bug: Orb not visually changing** — root cause found:
  - Background gradient never changed between states (only box-shadow did — barely visible)
  - Scale differences too subtle (1-5% on 300px orb)
  - JS state classes could leak (multiple states simultaneously)
  - **Fixes applied:**
    - Distinct background gradients per state: cyan (idle), orange (listening), purple (thinking), bright cyan (speaking)
    - More dramatic animations: speaking pulses 1.0→1.12→0.97, thinking wobbles ±2deg
    - Added `background` to CSS transition for smooth color shifts
    - Fixed JS to remove all other state classes before adding new one
- **Dashboard tools added:**
  - `open_dashboard` — opens client engagement dashboard (`~/.hermes/dashboard/index.html`)
  - `open_briefing` — opens daily briefing (`~/.hermes/daily-briefing/index.html`)
  - `refresh_dashboard` — runs refresh.sh + opens
  - `refresh_briefing` — runs collect + generate scripts + opens
  - Classifier prompt updated with trigger phrases

### Complete UI Rewrite — Canvas-based JARVIS Animation
- **Replaced CSS class-based orb with full Canvas 2D animation engine**
  - Studied FatihMakes ui.py: exponential lerp toward random targets, halo alpha compositing
  - Studied Mark XXXIX 6-state system: idle, listening, thinking, speaking, processing, muted
- **New animation system:**
  - Smooth color lerping between states (not instant class swaps)
  - Radiating pulse waves that expand outward from orb during active states
  - 3 orbital rings rotating at different speeds + direction, with dots
  - Radial gradient orb with inner highlight and edge glow
  - Soft halo bloom behind orb that intensifies per state
- **5 visual states with distinct colors + behaviors:**
  - Idle: cyan, gentle breathing (scale 0.98–1.02), no pulse waves, slow rings
  - Listening: orange, faster pulse (0.96–1.06), pulse waves every 800ms, faster rings
  - Thinking: purple, medium pulse with wobble, waves every 1200ms, fast rings
  - Speaking: bright cyan, dramatic pulse (0.94–1.10), rapid waves every 400ms
  - Processing: purple, subtle pulse, waves every 1000ms, fastest rings
- **Status text color matches state:** cyan, orange, purple
- **Name usage fix:** Only use Carolyn's name at start/end of conversation, not every reply

### Status: ✅ v3 Running
- Server starts and serves UI
- TTS confirmed working with British voice
- All imports validated
- UI accessible at http://127.0.0.1:8766

---

### API Key & LLM Fix
- Set OpenRouter API key in `.env`
- Switched LLM from Claude Sonnet 4 (too slow, 15s+ timeouts) to **Claude 3.5 Haiku** (sub-second responses)
- Bumped aiohttp timeout to 30s as safety net
- Confirmed LLM responds correctly with British persona
- Server restarted with key loaded — fully operational

---

## Backlog / Future Enhancements
- [ ] Always-on listening mode (no button press needed)
- [ ] Wake word detection via streaming (like "Hey Siri")
- [ ] Desktop shortcut / menu bar app
- [ ] Connect to Hermes CLI tools (terminal, file ops, web search)
- [ ] Screen awareness (screenshot + vision analysis)
- [ ] Interruptible TTS (stop mid-sentence on new voice input)
- [ ] Memory persistence (save/load conversation context)
- [ ] Multiple voice options (toggle British voices)
- [ ] Dark/light theme toggle
- [ ] Mobile-responsive layout
- [ ] Notification sounds / chimes
- [ ] Integration with Apple Calendar, Reminders, etc.

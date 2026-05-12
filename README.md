# HERMES — Voice Intelligence System

A JARVIS-inspired British AI voice assistant with an animated orb UI, wake word detection, and full local tool execution.

Built as a voice/visual frontend for [Hermes](https://github.com/cklein08), the CLI AI agent.

![Python](https://img.shields.io/badge/Python-3.11+-blue)
![License](https://img.shields.io/badge/License-Personal_Use-green)

---

## Features

### Voice
- **Wake word detection** — say "Hermes" to activate, then speak naturally
- **Conversation mode** — once active, follow-up commands don't need the wake word (2-min timeout)
- **Whisper STT** — OpenAI Whisper runs locally/offline for speech-to-text
- **British TTS** — Microsoft Edge Neural voice (`en-GB-RyanNeural`) for spoken responses
- **Hybrid input** — seamlessly switch between voice (mic button) and keyboard

### Animated UI
Canvas 2D orb rendered at 60fps with smooth state transitions:

| State | Color | Behavior |
|-------|-------|----------|
| **Idle** | Cyan | Gentle breathing, soft halo, slow orbital rings |
| **Listening** | Orange | Faster pulse, pulse waves radiate outward every 800ms |
| **Thinking** | Purple | Medium pulse, waves every 1.2s, fastest ring spin |
| **Speaking** | Bright Cyan | Dramatic pulsing (0.94→1.10 scale), rapid waves every 400ms |
| **Processing** | Purple | Subtle pulse, waves every 1s |

All color transitions lerp smoothly between states. Three orbital rings rotate at different speeds with tracking dots. Typewriter text effect on responses.

### Tool Execution
Not just a chatbot — Hermes classifies your intent via LLM and executes real tools locally:

| Command | Tool | What it does |
|---------|------|-------------|
| "Check my emails" | `himalaya` | Lists inbox via IMAP |
| "Send an email to..." | `himalaya` | Composes and sends |
| "What's on my calendar?" | `acal` | Shows today's events from Apple Calendar |
| "Remind me to..." | `remindctl` | Creates an Apple Reminder |
| "Open my dashboard" | `open` | Opens client engagement dashboard |
| "Show my daily briefing" | `open` | Opens daily briefing dashboard |
| "Search for..." | `curl` | Web search via DuckDuckGo |
| "Run [command]" | `terminal` | Executes shell commands (with safety blocklist) |
| General chat | LLM | Conversational British wit |

Two-stage LLM pipeline: **Classifier** (picks tool + params) → **Executor** (runs locally) → **Formatter** (crafts spoken response).

---

## Requirements

- **Python 3.11+** (tested on 3.13)
- **macOS** (uses `acal`, `remindctl`, `himalaya` CLI tools)
- **Microphone** for voice input
- **OpenRouter API key** (free tier works — uses Claude 3.5 Haiku)

### CLI Tools (for full functionality)
| Tool | Purpose | Install |
|------|---------|---------|
| `himalaya` | Email via IMAP/SMTP | `brew install himalaya` |
| `acal` | Apple Calendar CLI | `brew install acal` |
| `remindctl` | Apple Reminders CLI | `brew install remindctl` |

These are optional — chat and web search work without them.

---

## Quick Start

```bash
# Clone
git clone https://github.com/cklein08/hermes-voice.git
cd hermes-voice

# Setup
python3 -m venv venv
source venv/bin/activate
pip install edge-tts sounddevice soundfile numpy websockets aiohttp openai-whisper

# Configure
echo "OPENROUTER_API_KEY=your_key_here" > .env

# Run
./start.sh
```

Open **http://127.0.0.1:8766** in your browser.

### Or just:
```bash
./start.sh
```
The launcher handles venv activation, key loading, and server startup.

---

## Usage

### Voice
1. Click **MIC**, speak your command, click **STOP**
2. Or say **"Hermes"** followed by your command
3. Follow-up commands don't need the wake word (stays active for 2 minutes)

### Keyboard
Type in the text bar and hit **Enter** or click **SEND**.

### Stop Speaking
Say "mute", "stop", "quit", or "exit" to interrupt.

---

## Architecture

```
Browser (index.html)          Server (server.py)
┌─────────────────┐          ┌──────────────────────┐
│  Canvas 2D Orb  │          │  WebSocket (8765)     │
│  State Machine  │◄────────►│  Intent Classifier    │
│  Audio Record   │   WS     │  Tool Executor        │
│  Audio Playback │          │  Whisper STT          │
│  Chat Log       │          │  Edge TTS             │
└─────────────────┘          │  OpenRouter LLM       │
                             └──────────────────────┘
                                      │
                             ┌────────┴────────┐
                             │  Local Tools     │
                             │  himalaya, acal  │
                             │  remindctl, bash │
                             └─────────────────┘
```

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENROUTER_API_KEY` | — | Required. Set in `.env` or environment |
| `BRITISH_VOICE` | `en-GB-RyanNeural` | Edge TTS voice ID |
| `WHISPER_MODEL` | `base` | Options: `tiny`, `base`, `small`, `medium` |
| `WS_PORT` | `8765` | WebSocket server port |
| `HTTP_PORT` | `8766` | Web UI server port |

### Available British Voices
- `en-GB-RyanNeural` — Male (default)
- `en-GB-ThomasNeural` — Male
- `en-GB-SoniaNeural` — Female
- `en-GB-LibbyNeural` — Female
- `en-GB-MaisieNeural` — Female

---

## Inspired By

- [FatihMakes / Mark-XXXIX-OR](https://github.com/FatihMakes/Mark-XXXIX-OR) — JARVIS AI assistant
- [FatihMakes YouTube](https://www.youtube.com/@fatihmakes) — Build tutorials

---

## License

Personal use only. Not for commercial distribution.

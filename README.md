# HERMES — Voice Intelligence System

A JARVIS-inspired British AI voice assistant with an animated orb UI, wake word detection, and full local tool execution.

![Python](https://img.shields.io/badge/Python-3.11+-blue)
![macOS](https://img.shields.io/badge/macOS-supported-green)
![Linux](https://img.shields.io/badge/Linux-supported-green)

---

## 30-Second Install

```bash
git clone https://github.com/cklein08/hermes-voice.git
cd hermes-voice
./install.sh
```

That's it. The installer handles everything:
- ✅ Detects your OS and Python version
- ✅ Installs system dependencies (portaudio, ffmpeg)
- ✅ Creates a Python virtual environment
- ✅ Installs all packages
- ✅ Launches an interactive setup wizard

### Then to start:
```bash
./start.sh
```
Opens **http://127.0.0.1:8766** in your browser automatically.

---

## Setup Wizard

The wizard walks you through everything with no technical knowledge needed:

```
🎯 Step 1: What's your name?
🔑 Step 2: Paste your OpenRouter API key
🎤 Step 3: Pick your British voice (with live preview!)
📧 Step 4: Connect your email (optional)
📅 Step 5: Connect your calendar (optional)
⏰ Step 6: Connect reminders (optional)
🎛️ Step 7: Choose a preset
📝 Step 8: Connect NotePlan (optional)
```

### Presets

| Preset | What's included |
|--------|----------------|
| **Minimal** | Chat + voice only. No tools. |
| **Personal** | Chat + email + calendar + reminders |
| **Adobe EA** | Everything — dashboards, NotePlan, Salesforce context, email, calendar, reminders |
| **Custom** | Pick and choose what you want |

---

## Features

### 🎤 Voice
- **Wake word** — say "Hermes" to activate, then speak naturally
- **Conversation mode** — follow-ups don't need the wake word (2-min timeout)
- **Whisper STT** — runs locally/offline for speech-to-text
- **British TTS** — 5 neural voices to choose from
- **Hybrid input** — voice or keyboard, seamlessly

### 🔮 Animated UI
Canvas 2D orb rendered at 60fps with smooth state transitions:

| State | Color | What's happening |
|-------|-------|----------|
| Idle | Cyan | Gentle breathing, soft halo |
| Listening | Orange | Pulse waves radiate outward |
| Thinking | Purple | Fast ring spin, waves every 1.2s |
| Speaking | Bright Cyan | Dramatic pulsing, rapid waves |
| Processing | Purple | Subtle pulse, tool executing |

### 🛠️ Tools
Hermes doesn't just chat — it executes real commands on your machine:

| Say this | What happens |
|----------|-------------|
| "Check my emails" | Reads your inbox |
| "Send an email to..." | Composes and sends |
| "What's on my calendar?" | Shows today's events |
| "Remind me to..." | Creates a reminder |
| "Open my dashboard" | Opens client dashboard |
| "Show my daily briefing" | Opens briefing dashboard |
| "Search my notes for..." | Searches NotePlan |
| "Search the web for..." | Web search |

---

## Requirements

- **Python 3.11+**
- **macOS** or **Linux** (macOS recommended for full feature set)
- **Microphone** for voice input
- **OpenRouter API key** — free at [openrouter.ai/keys](https://openrouter.ai/keys)

### Optional CLI Tools
The setup wizard will check for and offer to install these:

| Tool | What for | Install |
|------|----------|---------|
| `himalaya` | Email | `brew install himalaya` |
| `acal` | Calendar | `brew install acal` |
| `remindctl` | Reminders | `brew install remindctl` |

---

## Available Voices

| Voice | Gender | ID |
|-------|--------|-----|
| Ryan | Male | `en-GB-RyanNeural` |
| Thomas | Male | `en-GB-ThomasNeural` |
| Sonia | Female | `en-GB-SoniaNeural` |
| Libby | Female | `en-GB-LibbyNeural` |
| Maisie | Female | `en-GB-MaisieNeural` |

The wizard lets you preview each voice before choosing.

---

## Architecture

```
Browser (index.html)            Server (server.py)
┌──────────────────┐           ┌───────────────────────┐
│  Canvas 2D Orb   │           │  WebSocket (8765)      │
│  5 Visual States │◄─────────►│  Config-driven Tools   │
│  Audio Record    │    WS     │  Whisper STT (local)   │
│  Audio Playback  │           │  Edge TTS (British)    │
│  Chat Log        │           │  OpenRouter LLM        │
└──────────────────┘           └───────────┬───────────┘
                                           │
                    ┌──────────────────────┤
                    │                      │
            ┌───────┴──────┐    ┌──────────┴──────────┐
            │ Local Tools  │    │  Plugins             │
            │ himalaya     │    │  Client Dashboard    │
            │ acal         │    │  Daily Briefing      │
            │ remindctl    │    │  NotePlan            │
            │ terminal     │    │  (your own!)         │
            └──────────────┘    └─────────────────────┘
```

---

## Configuration

All config lives in `config.json` (created by the wizard). To reconfigure:

```bash
source venv/bin/activate
python3 setup_wizard.py
```

### Manual Config

Copy the example and edit:
```bash
cp config.example.json config.json
```

See `config.example.json` for the full schema.

---

## Inspired By

- [FatihMakes / Mark-XXXIX-OR](https://github.com/FatihMakes/Mark-XXXIX-OR) — JARVIS AI assistant
- [FatihMakes YouTube](https://www.youtube.com/@fatihmakes) — Build tutorials

---

## License

Personal use only. Not for commercial distribution.

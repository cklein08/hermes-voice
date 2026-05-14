# 🔮 HERMES — Your Personal AI Voice Assistant

> *"Good evening. Hermes at your service."*

A JARVIS-inspired AI assistant that **listens to your voice**, **talks back in a British accent**, and **actually does things** — checks your email, manages your calendar, opens dashboards, searches your notes, and more.

Built with a beautiful animated orb UI that changes color and behavior based on what Hermes is doing.

![Python](https://img.shields.io/badge/Python-3.11+-blue)
![macOS](https://img.shields.io/badge/macOS-supported-green)
![Linux](https://img.shields.io/badge/Linux-supported-green)

---

## ⚡ Get Started in 3 Steps

### Step 1: Clone the repo
```bash
git clone https://github.com/cklein08/hermes-voice.git
cd hermes-voice
```

### Step 2: Run the installer
```bash
./install.sh
```
This automatically:
- Checks your system and installs everything needed
- Walks you through a friendly setup wizard (no coding required)
- Lets you pick your voice and hear a preview
- Connects your email, calendar, and tools (all optional)

### Step 3: Start Hermes
```bash
./start.sh
```
Your browser opens automatically. That's it — start talking.

---

## 🗣️ How to Talk to Hermes

### By Voice
1. Click the **MIC** button
2. Say your command
3. Click **STOP**
4. Watch the orb animate and hear the British reply

### With a Wake Word
Say **"Hermes"** followed by your command — like *"Hermes, check my emails"*.

Once you're in a conversation, you don't need to say "Hermes" again — just keep talking naturally. The conversation stays active for 2 minutes.

### By Typing
Type in the text bar at the bottom and press **Enter**.

---

## 💬 What Can Hermes Do?

Just ask naturally. Here are some examples:

| You say... | Hermes does... |
|-----------|---------------|
| *"Check my emails"* | Opens your inbox and reads out the latest |
| *"Send an email to John about the meeting"* | Composes and sends it |
| *"What's on my calendar today?"* | Lists your meetings and events |
| *"Remind me to call Sarah at 3pm"* | Creates a reminder on your phone |
| *"Open my dashboard"* | Opens your client engagement dashboard |
| *"Show my daily briefing"* | Opens your daily briefing dashboard |
| *"Search my notes for Project Drago"* | Searches your NotePlan notes |
| *"What's the latest on AI agents?"* | Searches the web |
| *"How much disk space do I have?"* | Runs the command and tells you |
| *"Tell me a joke"* | Just chats with dry British wit |

---

## 🔮 The Animated Orb

The orb in the center isn't just decoration — it tells you what Hermes is doing:

| Orb Color | State | What's happening |
|-----------|-------|-----------------|
| 🔵 **Cyan** (gentle pulse) | Idle | Waiting for your command |
| 🟠 **Orange** (waves radiating) | Listening | Recording your voice |
| 🟣 **Purple** (fast spin) | Thinking | Processing your request |
| 💎 **Bright Cyan** (dramatic pulse) | Speaking | Talking back to you |
| 🟣 **Purple** (subtle pulse) | Processing | Running a tool |

Colors transition smoothly between states. Three orbital rings spin around the orb at different speeds with tracking dots.

---

## 🎛️ Setup Presets

During setup, you'll choose a preset that matches how you want to use Hermes:

| Preset | Best for | What's included |
|--------|----------|----------------|
| **Minimal** | Just want a voice chatbot | Chat + voice only |
| **Personal** | Daily life assistant | + Email, calendar, reminders |
| **Adobe EA** | Adobe Enterprise Architects | + Client dashboard, daily briefing, NotePlan, Salesforce context |
| **Custom** | Power users | Pick exactly what you want |

You can always re-run the wizard later:
```bash
source venv/bin/activate
python3 setup_wizard.py
```

---

## 🎤 Choose Your Voice

Hermes comes with 5 British neural voices. The wizard lets you preview each one:

| Voice | Gender | Vibe |
|-------|--------|------|
| **Ryan** | Male | Warm, professional (default) |
| **Thomas** | Male | Calm, measured |
| **Sonia** | Female | Confident, clear |
| **Libby** | Female | Friendly, approachable |
| **Maisie** | Female | Light, upbeat |

---

## 🔧 What You'll Need

| Requirement | Details |
|------------|---------|
| **Computer** | Mac (recommended) or Linux |
| **Python** | 3.11 or newer (the installer checks for you) |
| **Microphone** | For voice commands |
| **API Key** | Free from [openrouter.ai/keys](https://openrouter.ai/keys) — takes 30 seconds |

### LLM Model

Hermes uses **Google Gemini 2.5 Flash** by default via OpenRouter — fast, cheap (~$0.15/$0.60 per M tokens), and great at tool routing for voice assistants.

To change the model, edit `config.json`:
```json
"llm_model": "google/gemini-2.5-flash"
```

Other options:
| Model | Cost (in/out per M tokens) | Best for |
|-------|---------------------------|----------|
| `google/gemini-2.5-flash` | $0.15 / $0.60 | Default — fast, cheap, good at JSON |
| `anthropic/claude-sonnet-4` | $3 / $15 | Smarter multi-turn, higher cost |
| `google/gemini-2.5-pro` | $1.25 / $10 | Complex reasoning, mid-range cost |

### Optional Tools (for full power)

These unlock email, calendar, and reminder features. The wizard will offer to install them for you:

| Tool | What it does | Auto-install? |
|------|-------------|---------------|
| `himalaya` | Reads and sends email | ✅ Yes (via Homebrew) |
| `acal` | Reads Apple Calendar | ✅ Yes (via Homebrew) |
| `remindctl` | Creates Apple Reminders | ✅ Yes (via Homebrew) |

---

## 📁 Project Structure

```
hermes-voice/
├── install.sh           ← Run this first (one-click installer)
├── start.sh             ← Run this to start Hermes
├── setup_wizard.py      ← Interactive setup (runs automatically)
├── server.py            ← Backend: voice processing, LLM, tools
├── ui/
│   └── index.html       ← The animated orb UI
├── plugins/
│   ├── dashboard/       ← Client dashboard plugin
│   └── briefing/        ← Daily briefing plugin
├── config.json          ← Your personal config (created by wizard)
├── config.example.json  ← Template for manual setup
├── .env                 ← Your API key (auto-generated, private)
├── PROGRESS.md          ← Development changelog
└── README.md            ← You are here
```

---

## 🏗️ How It Works (Under the Hood)

```
  Your Voice / Text                    Your Browser
       │                              ┌──────────────┐
       ▼                              │  Animated    │
  ┌─────────┐    WebSocket    ┌───────│  Orb UI      │
  │ Whisper  │◄──────────────►│       │  Chat Log    │
  │ (local)  │                │       │  Audio Play  │
  └────┬─────┘                │       └──────────────┘
       │ text                 │
       ▼                      │  Hermes Server
  ┌─────────────┐             │  (server.py)
  │ LLM Intent  │             │
  │ Classifier  │─────────────┘
  └────┬────────┘
       │ tool + params
       ▼
  ┌─────────────┐     ┌──────────────┐
  │ Tool        │────►│ himalaya     │ email
  │ Executor    │────►│ acal         │ calendar
  │             │────►│ remindctl    │ reminders
  │             │────►│ NotePlan     │ notes
  │             │────►│ terminal     │ commands
  └────┬────────┘     └──────────────┘
       │ result
       ▼
  ┌─────────────┐
  │ LLM Response│
  │ Formatter   │──► Text shown instantly
  └────┬────────┘
       │
       ▼
  ┌─────────────┐
  │ Edge TTS    │──► British voice plays
  │ (neural)    │
  └─────────────┘
```

1. **You speak** → Whisper transcribes locally (no data sent anywhere)
2. **LLM classifies** your intent and picks the right tool
3. **Tool executes** on your machine (email, calendar, etc.)
4. **LLM formats** the result into a natural spoken response
5. **Edge TTS** speaks it back in your chosen British voice
6. **The orb** animates through each state so you always know what's happening

---

## 🔄 Reconfigure Anytime

```bash
# Re-run the setup wizard
source venv/bin/activate
python3 setup_wizard.py

# Or edit config directly
nano config.json
```

---

## 🙏 Credits

Inspired by [FatihMakes](https://www.youtube.com/@fatihmakes) and the [JARVIS Mark XXXIX](https://github.com/FatihMakes/Mark-XXXIX-OR) project.

---

## 📄 License

Personal use only. Not for commercial distribution.

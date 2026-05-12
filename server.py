"""
HERMES Voice Assistant — Backend Server (v4 — config-driven)
British-voiced AI assistant with wake word detection, Whisper STT, Edge TTS.
Routes commands through local tools: email, calendar, reminders, web search, terminal.
Loads configuration from config.json — run setup wizard if missing.
"""

import asyncio
import json
import os
import re
import subprocess
import tempfile
import threading
import time
import glob
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler

import numpy as np
import edge_tts
import whisper
import websockets

# ── Config Loading ───────────────────────────────────────────
BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"


def load_config():
    """Load config.json or exit with instructions."""
    if not CONFIG_PATH.exists():
        print("━" * 50)
        print("  ERROR: config.json not found!")
        print("  Please run the setup wizard first:")
        print("    python3 setup.py")
        print("━" * 50)
        raise SystemExit(1)
    with open(CONFIG_PATH) as f:
        return json.load(f)


CONFIG = load_config()

# ── Extract config values ────────────────────────────────────
USER_NAME = CONFIG.get("user_name", "User")
USER_ADDRESS = CONFIG.get("address_preference", USER_NAME)
USER_EMAIL = CONFIG.get("email", "")
USER_WORK_EMAIL = CONFIG.get("work_email", "")
USER_GENDER = CONFIG.get("gender", "")
VOICE = CONFIG.get("voice", "en-GB-RyanNeural")
WHISPER_MODEL = CONFIG.get("whisper_model", "base")
OPENROUTER_API_KEY = CONFIG.get("openrouter_api_key", "") or os.environ.get("OPENROUTER_API_KEY", "")
WAKE_WORD = CONFIG.get("wake_word", "hermes")
HOST = CONFIG.get("host", "127.0.0.1")
WS_PORT = CONFIG.get("ws_port", 8765)
HTTP_PORT = CONFIG.get("http_port", 8766)
ENABLED_MODULES = CONFIG.get("modules", {})
NOTEPLAN_PATH = CONFIG.get("noteplan_path", "")
HERMES_BASE = CONFIG.get("hermes_base", str(Path.home() / ".hermes"))

# Gender-aware address rules
_gender_hint = ""
if USER_GENDER.lower() in ("female", "woman", "f"):
    _gender_hint = f'The user is {USER_NAME}, a woman. Never call her "sir".'
elif USER_GENDER.lower() in ("male", "man", "m"):
    _gender_hint = f'The user is {USER_NAME}, a man. Never call him "ma\'am".'
else:
    _gender_hint = f'The user is {USER_NAME}.'

_name_usage = f'Use "{USER_ADDRESS}" sparingly — only at conversation start, mid-point, or sign-off. Most replies need no name at all.'


# ── Dynamic Prompt Building ──────────────────────────────────

def _build_tool_list():
    """Build the available tools portion of the classifier prompt based on enabled modules."""
    tools = []

    if ENABLED_MODULES.get("email", {}).get("enabled", False):
        tools.append('- "email_list": List recent emails (inbox). No params needed.')
        tools.append('- "email_send": Send an email. Params: {"to": "address", "subject": "...", "body": "..."}')
        tools.append('- "email_search": Search emails by keyword. Params: {"query": "search terms"}')
        tools.append('- "email_read": Read a specific email by ID. Params: {"id": "email_id_number"}')

    if ENABLED_MODULES.get("calendar", {}).get("enabled", False):
        tools.append('- "calendar_today": Show today\'s calendar events. No params needed.')
        tools.append('- "calendar_list": Show upcoming events for N days. Params: {"days": number}')

    if ENABLED_MODULES.get("reminders", {}).get("enabled", False):
        tools.append('- "reminder_list": List all reminders across all lists. No params needed.')
        tools.append('- "reminder_add": Add a reminder. Params: {"title": "...", "list": "optional list name"}')

    if ENABLED_MODULES.get("web_search", {}).get("enabled", False):
        tools.append('- "web_search": Search the web. Params: {"query": "search terms"}')

    if ENABLED_MODULES.get("terminal", {}).get("enabled", False):
        tools.append('- "terminal": Run a macOS shell command. Params: {"command": "..."}')

    if ENABLED_MODULES.get("dashboard", {}).get("enabled", False):
        tools.append('- "open_dashboard": Open the client engagement dashboard in browser. No params needed.')
        tools.append('- "refresh_dashboard": Refresh/regenerate the client dashboard data. No params needed.')

    if ENABLED_MODULES.get("briefing", {}).get("enabled", False):
        tools.append('- "open_briefing": Open the daily briefing dashboard in browser. No params needed.')
        tools.append('- "refresh_briefing": Refresh/regenerate the daily briefing data. No params needed.')

    if ENABLED_MODULES.get("noteplan", {}).get("enabled", False):
        tools.append('- "noteplan_search": Search NotePlan notes by keyword. Params: {"query": "search terms"}')
        tools.append('- "noteplan_read": Read a specific NotePlan note. Params: {"file": "relative/path/to/note.md"}')

    # Chat is always available
    tools.append('- "chat": Just a conversational response, no tool needed. Params: {"reply": "your response"}')
    return "\n".join(tools)


def _build_tool_instructions():
    """Build context-aware instructions for the classifier."""
    instructions = []

    if ENABLED_MODULES.get("email", {}).get("enabled", False):
        email_addr = USER_EMAIL or "the user's email"
        work_email = USER_WORK_EMAIL
        email_note = f"The user's email is {email_addr}."
        if work_email:
            email_note += f" Their work email is {work_email}."
        instructions.append(email_note)
        instructions.append(f'When they say "send email" or "check my email" or "do I have any emails", USE the email tools — do NOT say you can\'t.')

    if ENABLED_MODULES.get("calendar", {}).get("enabled", False):
        instructions.append("When they ask about their schedule/meetings/calendar, USE the calendar tools.")

    if ENABLED_MODULES.get("reminders", {}).get("enabled", False):
        instructions.append("When they ask to remind them of something, USE reminder_add.")

    if ENABLED_MODULES.get("dashboard", {}).get("enabled", False):
        instructions.append('When they say "dashboard", "client dashboard", "engagement dashboard" → use open_dashboard.')
        instructions.append('When they say "refresh dashboard" or "update dashboard" → use refresh_dashboard.')

    if ENABLED_MODULES.get("briefing", {}).get("enabled", False):
        instructions.append('When they say "briefing", "daily brief", "daily briefing" → use open_briefing.')
        instructions.append('When they say "refresh briefing" or "update briefing" → use refresh_briefing.')

    if ENABLED_MODULES.get("noteplan", {}).get("enabled", False):
        instructions.append('When they ask to search notes, find a note, or look something up in their notes, USE noteplan_search.')
        instructions.append('When they ask to read a specific note or open a note, USE noteplan_read.')

    return "\n".join(instructions)


def build_classifier_prompt():
    """Build the full classifier system prompt from config."""
    tool_list = _build_tool_list()
    tool_instructions = _build_tool_instructions()

    # Determine which tools to list for the "prefer using tools" line
    tool_names = []
    if ENABLED_MODULES.get("email", {}).get("enabled"):
        tool_names.append("email")
    if ENABLED_MODULES.get("calendar", {}).get("enabled"):
        tool_names.append("calendar")
    if ENABLED_MODULES.get("reminders", {}).get("enabled"):
        tool_names.append("reminders")
    prefer_tools_line = ""
    if tool_names:
        prefer_tools_line = f"- For {', '.join(tool_names)} — prefer using the tools over saying you can't."

    return f"""You are Hermes, a British AI assistant with access to local tools on a macOS system.
Analyse the user's request and respond with a JSON object indicating the action to take.

Available tools:
{tool_list}

{tool_instructions}

IMPORTANT: 
- Respond ONLY with a JSON object: {{"tool": "tool_name", "params": {{...}}}}
- For "chat", include your full spoken response in params.reply
- Never use asterisk actions. Write only spoken words.
- Be concise (1-3 sentences) for chat responses.
- Use British English.
{prefer_tools_line}
- {_gender_hint} {_name_usage}"""


def build_response_prompt():
    """Build the response formatting prompt from config."""
    return f"""You are Hermes, a sophisticated British AI assistant. 
Given the tool output below, craft a concise spoken response (1-3 sentences).
Use British English. Never use asterisk actions. Only spoken words.
Be helpful and specific — summarise the key information from the tool output.
{_gender_hint} Don't use their name in every reply — only at start or end of conversation."""


CLASSIFIER_PROMPT = build_classifier_prompt()
RESPONSE_PROMPT = build_response_prompt()


# ── Globals ─────────────────────────────────────────────────────
whisper_model = None
conversation_history = []
_http_session = None


async def get_http_session():
    global _http_session
    import aiohttp
    if _http_session is None or _http_session.closed:
        _http_session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30)
        )
    return _http_session


def load_whisper():
    global whisper_model
    print(f"[Hermes] Loading Whisper '{WHISPER_MODEL}' model...")
    whisper_model = whisper.load_model(WHISPER_MODEL)
    print("[Hermes] Whisper model loaded.")


def transcribe_audio(audio_bytes):
    if whisper_model is None:
        return ""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        tmp_path = f.name
        f.write(audio_bytes)
    try:
        result = whisper_model.transcribe(tmp_path, language="en", fp16=False)
        return result.get("text", "").strip()
    except Exception as e:
        print(f"[Hermes] Transcription error: {e}")
        return ""
    finally:
        os.unlink(tmp_path)


def detect_wake_word(text):
    lower = text.lower()
    variants = ["hermes", "hermis", "hermés", "her mes", "hurmes"]
    for v in variants:
        if v in lower:
            idx = lower.index(v) + len(v)
            command = text[idx:].strip().lstrip(",").lstrip(".").strip()
            return True, command
    return False, text


async def generate_tts_complete(text):
    communicate = edge_tts.Communicate(text, VOICE, rate="+5%", pitch="+0Hz")
    audio_data = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_data.extend(chunk["data"])
    return bytes(audio_data)


# ── Tool Execution ──────────────────────────────────────────────

def run_local_command(cmd, timeout=15):
    """Run a shell command locally and return output."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, env={**os.environ, "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:" + os.environ.get("PATH", "")}
        )
        output = result.stdout.strip()
        if result.returncode != 0 and result.stderr:
            output += "\n" + result.stderr.strip()
        return output or "(no output)"
    except subprocess.TimeoutExpired:
        return "Command timed out."
    except FileNotFoundError as e:
        return f"Tool not found: {e}. Please install the required command-line tool."
    except Exception as e:
        return f"Error: {e}"


def _safe_tool(cmd, tool_name="tool", timeout=15):
    """Run a command with graceful error handling for missing tools."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, env={**os.environ, "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:" + os.environ.get("PATH", "")}
        )
        output = result.stdout.strip()
        if result.returncode != 0 and result.stderr:
            stderr = result.stderr.strip()
            # Check for "command not found" patterns
            if "not found" in stderr.lower() or "No such file" in stderr:
                return f"The '{tool_name}' command is not installed. Please install it to use this feature."
            output += "\n" + stderr
        return output or "(no output)"
    except FileNotFoundError:
        return f"The '{tool_name}' command is not installed. Please install it to use this feature."
    except subprocess.TimeoutExpired:
        return "Command timed out."
    except Exception as e:
        return f"Error running {tool_name}: {e}"


# ── NotePlan Tools ──────────────────────────────────────────────

def noteplan_search(query):
    """Search .txt/.md files in the NotePlan path by keyword."""
    if not NOTEPLAN_PATH:
        return "NotePlan path not configured. Please run the setup wizard."
    np_path = Path(NOTEPLAN_PATH).expanduser()
    if not np_path.exists():
        return f"NotePlan path not found: {np_path}"

    query_lower = query.lower()
    results = []
    # Search in Notes and Calendar directories
    for pattern in ["**/*.md", "**/*.txt"]:
        for fpath in np_path.glob(pattern):
            try:
                content = fpath.read_text(encoding="utf-8", errors="ignore")
                if query_lower in content.lower():
                    # Get first matching line for context
                    for line in content.split("\n"):
                        if query_lower in line.lower():
                            context = line.strip()[:120]
                            break
                    else:
                        context = content[:120].strip()
                    rel = fpath.relative_to(np_path)
                    results.append(f"• {rel}: {context}")
                    if len(results) >= 15:
                        break
            except Exception:
                continue
        if len(results) >= 15:
            break

    if not results:
        return f"No notes found matching '{query}'."
    return f"Found {len(results)} matching note(s):\n" + "\n".join(results)


def noteplan_read(file_path):
    """Read a specific note file from the NotePlan path."""
    if not NOTEPLAN_PATH:
        return "NotePlan path not configured. Please run the setup wizard."
    np_path = Path(NOTEPLAN_PATH).expanduser()
    target = np_path / file_path

    # Security: ensure the path doesn't escape NotePlan directory
    try:
        target.resolve().relative_to(np_path.resolve())
    except ValueError:
        return "Access denied: path is outside the NotePlan directory."

    if not target.exists():
        return f"Note not found: {file_path}"
    try:
        content = target.read_text(encoding="utf-8", errors="ignore")
        # Truncate very long notes
        if len(content) > 3000:
            content = content[:3000] + "\n... (truncated)"
        return content
    except Exception as e:
        return f"Error reading note: {e}"


# ── Dashboard/Briefing Plugin Tools ─────────────────────────────

PLUGINS_DIR = BASE_DIR / "plugins"


def open_dashboard():
    """Open the dashboard — check plugins dir first, fall back to hermes base."""
    plugin_index = PLUGINS_DIR / "dashboard" / "index.html"
    hermes_index = Path(HERMES_BASE) / "dashboard" / "index.html"
    if plugin_index.exists():
        run_local_command(f"open {plugin_index}")
        return "Client engagement dashboard opened in your browser."
    elif hermes_index.exists():
        run_local_command(f"open {hermes_index}")
        return "Client engagement dashboard opened in your browser."
    else:
        return "Dashboard not found. Please set up the dashboard plugin first."


def open_briefing():
    """Open the briefing — check plugins dir first, fall back to hermes base."""
    plugin_index = PLUGINS_DIR / "briefing" / "index.html"
    hermes_index = Path(HERMES_BASE) / "daily-briefing" / "index.html"
    if plugin_index.exists():
        run_local_command(f"open {plugin_index}")
        return "Daily briefing dashboard opened in your browser."
    elif hermes_index.exists():
        run_local_command(f"open {hermes_index}")
        return "Daily briefing dashboard opened in your browser."
    else:
        return "Briefing not found. Please set up the briefing plugin first."


def refresh_dashboard():
    """Refresh dashboard data."""
    plugin_refresh = PLUGINS_DIR / "dashboard" / "refresh.sh"
    hermes_refresh = Path(HERMES_BASE) / "scripts" / "dashboard" / "refresh.sh"
    if plugin_refresh.exists():
        output = _safe_tool(f"bash {plugin_refresh}", "dashboard-refresh", timeout=60)
    elif hermes_refresh.exists():
        output = _safe_tool(f"bash {hermes_refresh}", "dashboard-refresh", timeout=60)
    else:
        return "Dashboard refresh script not found."
    # Open after refresh
    open_dashboard()
    return f"Dashboard refreshed and opened. {output}"


def refresh_briefing():
    """Refresh briefing data."""
    plugin_dir = PLUGINS_DIR / "briefing"
    hermes_dir = Path(HERMES_BASE) / "scripts" / "daily-briefing"
    if (plugin_dir / "collect_briefing.py").exists():
        output = _safe_tool(f"cd {plugin_dir} && python3 collect_briefing.py && python3 generate_briefing.py", "briefing-refresh", timeout=60)
    elif hermes_dir.exists():
        output = _safe_tool(f"cd {hermes_dir} && python3 collect_briefing.py && python3 generate_briefing.py", "briefing-refresh", timeout=60)
    else:
        return "Briefing refresh scripts not found."
    open_briefing()
    return f"Daily briefing regenerated and opened. {output}"


# ── Tool Dispatch ───────────────────────────────────────────────

def execute_tool(tool, params):
    """Execute a local tool and return the output."""
    print(f"[Hermes] Executing tool: {tool} with params: {params}")

    # ── Email tools ──
    if tool == "email_list":
        if not ENABLED_MODULES.get("email", {}).get("enabled"):
            return "Email module is not enabled. Please enable it in setup."
        return _safe_tool("himalaya envelope list --account gmail -s 10", "himalaya")

    elif tool == "email_send":
        if not ENABLED_MODULES.get("email", {}).get("enabled"):
            return "Email module is not enabled."
        to = params.get("to", "")
        subject = params.get("subject", "")
        body = params.get("body", "")
        if not to or not subject:
            return "Missing recipient or subject for email."
        from_addr = USER_EMAIL or "user@example.com"
        tpl = f"From: {from_addr}\nTo: {to}\nSubject: {subject}\n\n{body}"
        cmd = f'echo {json.dumps(tpl)} | himalaya message send --account gmail'
        return _safe_tool(cmd, "himalaya")

    elif tool == "email_search":
        if not ENABLED_MODULES.get("email", {}).get("enabled"):
            return "Email module is not enabled."
        query = params.get("query", "")
        return _safe_tool(f'himalaya envelope list --account gmail -s 10 -q {json.dumps(query)}', "himalaya")

    elif tool == "email_read":
        if not ENABLED_MODULES.get("email", {}).get("enabled"):
            return "Email module is not enabled."
        id_num = params.get("id", "")
        if not id_num:
            return "Missing email ID."
        return _safe_tool(f'himalaya message read --account gmail {id_num}', "himalaya")

    # ── Calendar tools ──
    elif tool == "calendar_today":
        if not ENABLED_MODULES.get("calendar", {}).get("enabled"):
            return "Calendar module is not enabled."
        today = time.strftime("%Y-%m-%d")
        tomorrow = time.strftime("%Y-%m-%d", time.localtime(time.time() + 86400))
        return _safe_tool(f'acal events list --from {today} --to {tomorrow}', "acal")

    elif tool == "calendar_list":
        if not ENABLED_MODULES.get("calendar", {}).get("enabled"):
            return "Calendar module is not enabled."
        days = params.get("days", 3)
        today = time.strftime("%Y-%m-%d")
        end = time.strftime("%Y-%m-%d", time.localtime(time.time() + 86400 * days))
        return _safe_tool(f'acal events list --from {today} --to {end}', "acal")

    # ── Reminder tools ──
    elif tool == "reminder_list":
        if not ENABLED_MODULES.get("reminders", {}).get("enabled"):
            return "Reminders module is not enabled."
        return _safe_tool("remindctl list", "remindctl")

    elif tool == "reminder_add":
        if not ENABLED_MODULES.get("reminders", {}).get("enabled"):
            return "Reminders module is not enabled."
        title = params.get("title", "")
        list_name = params.get("list", "Reminders")
        if not title:
            return "Missing reminder title."
        cmd = f'remindctl add --list {json.dumps(list_name)} {json.dumps(title)}'
        return _safe_tool(cmd, "remindctl")

    # ── Web search ──
    elif tool == "web_search":
        if not ENABLED_MODULES.get("web_search", {}).get("enabled"):
            return "Web search module is not enabled."
        query = params.get("query", "")
        return run_local_command(f'curl -s "https://html.duckduckgo.com/html/?q={query}" | grep -oP \'(?<=class="result__a" href=").*?(?=")\' | head -5 2>/dev/null || echo "Search completed for: {query}"')

    # ── Terminal ──
    elif tool == "terminal":
        if not ENABLED_MODULES.get("terminal", {}).get("enabled"):
            return "Terminal module is not enabled."
        command = params.get("command", "")
        if not command:
            return "No command specified."
        dangerous = ["rm -rf /", "mkfs", "dd if=", "> /dev/"]
        for d in dangerous:
            if d in command:
                return "I'm afraid I can't execute that command. Safety first."
        return run_local_command(command)

    # ── Dashboard ──
    elif tool == "open_dashboard":
        if not ENABLED_MODULES.get("dashboard", {}).get("enabled"):
            return "Dashboard module is not enabled."
        return open_dashboard()

    elif tool == "refresh_dashboard":
        if not ENABLED_MODULES.get("dashboard", {}).get("enabled"):
            return "Dashboard module is not enabled."
        return refresh_dashboard()

    # ── Briefing ──
    elif tool == "open_briefing":
        if not ENABLED_MODULES.get("briefing", {}).get("enabled"):
            return "Briefing module is not enabled."
        return open_briefing()

    elif tool == "refresh_briefing":
        if not ENABLED_MODULES.get("briefing", {}).get("enabled"):
            return "Briefing module is not enabled."
        return refresh_briefing()

    # ── NotePlan ──
    elif tool == "noteplan_search":
        if not ENABLED_MODULES.get("noteplan", {}).get("enabled"):
            return "NotePlan module is not enabled."
        query = params.get("query", "")
        if not query:
            return "Missing search query."
        return noteplan_search(query)

    elif tool == "noteplan_read":
        if not ENABLED_MODULES.get("noteplan", {}).get("enabled"):
            return "NotePlan module is not enabled."
        file_path = params.get("file", "")
        if not file_path:
            return "Missing file path."
        return noteplan_read(file_path)

    # ── Chat (always available) ──
    elif tool == "chat":
        return params.get("reply", "I'm here. How can I help?")

    else:
        return f"Unknown tool: {tool}"


# ── Token Tracking ───────────────────────────────────────────
token_usage = {"input": 0, "output": 0}

# ── LLM Calls ──────────────────────────────────────────────────

async def call_llm(messages, max_tokens=500):
    """Call OpenRouter LLM."""
    if not OPENROUTER_API_KEY:
        return None
    try:
        session = await get_http_session()
        async with session.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "anthropic/claude-3.5-haiku",
                "messages": messages,
                "temperature": 0.3,
                "max_tokens": max_tokens,
            },
        ) as resp:
            data = await resp.json()
            # Track token usage
            usage = data.get("usage", {})
            token_usage["input"] += usage.get("prompt_tokens", 0)
            token_usage["output"] += usage.get("completion_tokens", 0)
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"[Hermes] LLM error: {e}")
        return None


async def classify_and_execute(user_message):
    """Use LLM to classify intent, execute tool, then format response."""
    global conversation_history

    conversation_history.append({"role": "user", "content": user_message})
    if len(conversation_history) > 20:
        conversation_history = conversation_history[-20:]

    # Step 1: Classify intent
    classify_messages = [
        {"role": "system", "content": CLASSIFIER_PROMPT},
    ] + conversation_history[-6:]  # Last 3 exchanges for context

    raw = await call_llm(classify_messages, max_tokens=500)
    if not raw:
        reply = "I'm afraid I can't reach my thinking engines at the moment."
        conversation_history.append({"role": "assistant", "content": reply})
        return reply

    print(f"[Hermes] Classifier output: {raw}")

    # Parse JSON from LLM response
    try:
        # Handle markdown code blocks
        cleaned = re.sub(r'```json\s*', '', raw)
        cleaned = re.sub(r'```\s*', '', cleaned)
        # Find JSON object
        match = re.search(r'\{.*\}', cleaned, re.DOTALL)
        if match:
            action = json.loads(match.group())
        else:
            raise ValueError("No JSON found")
    except (json.JSONDecodeError, ValueError) as e:
        print(f"[Hermes] JSON parse error: {e}, raw: {raw}")
        # Fallback: treat as chat
        reply = raw if len(raw) < 500 else "I'm not quite sure what to do with that. Could you rephrase?"
        conversation_history.append({"role": "assistant", "content": reply})
        return reply

    tool = action.get("tool", "chat")
    params = action.get("params", {})

    # Step 2: Execute tool
    if tool == "chat":
        reply = params.get("reply", "How may I help you?")
        conversation_history.append({"role": "assistant", "content": reply})
        return reply

    # Run tool in thread pool (blocking I/O)
    loop = asyncio.get_event_loop()
    tool_output = await loop.run_in_executor(None, execute_tool, tool, params)
    print(f"[Hermes] Tool output ({tool}): {tool_output[:200]}")

    # Step 3: Format tool output into a spoken response
    format_messages = [
        {"role": "system", "content": RESPONSE_PROMPT},
        {"role": "user", "content": f"User asked: {user_message}\n\nTool used: {tool}\nTool output:\n{tool_output[:1500]}"},
    ]

    reply = await call_llm(format_messages, max_tokens=300)
    if not reply:
        # Fallback: just return raw output trimmed
        reply = f"Here's what I found: {tool_output[:200]}"

    conversation_history.append({"role": "assistant", "content": reply})
    return reply


# ── Command Handler ─────────────────────────────────────────────

async def respond_to_command(websocket, command):
    """Handle a command: classify → execute tool → format → TTS."""
    t0 = time.time()

    reply = await classify_and_execute(command)
    t1 = time.time()
    print(f'[Hermes] Total LLM+Tool: {t1-t0:.2f}s → "{reply}"')

    # Send text IMMEDIATELY
    await websocket.send(json.dumps({
        "type": "response",
        "text": reply
    }))

    # Generate and send TTS
    await websocket.send(json.dumps({"type": "tts_start"}))
    audio_data = await generate_tts_complete(reply)
    t2 = time.time()
    print(f"[Hermes] TTS: {t2-t1:.2f}s ({len(audio_data)} bytes)")

    await websocket.send(audio_data)
    await websocket.send(json.dumps({"type": "tts_end"}))
    print(f"[Hermes] Total: {t2-t0:.2f}s")


# ── WebSocket Server ────────────────────────────────────────────

async def handle_client(websocket):
    print("[Hermes] Client connected.")
    await websocket.send(json.dumps({
        "type": "status",
        "message": "Hermes online. All systems operational."
    }))

    in_conversation = False
    last_interaction = 0
    CONVERSATION_TIMEOUT = 120
    mic_activated = False

    try:
        async for message in websocket:
            if isinstance(message, str):
                data = json.loads(message)
                if data.get("type") == "text_command":
                    command = data.get("text", "")
                    print(f"[Hermes] Text command: '{command}'")
                    in_conversation = True
                    last_interaction = time.time()
                    await respond_to_command(websocket, command)

                elif data.get("type") == "mic_activate":
                    mic_activated = True

                elif data.get("type") == "clear_history":
                    conversation_history.clear()
                    in_conversation = False
                    await websocket.send(json.dumps({
                        "type": "status",
                        "message": "Conversation history cleared."
                    }))
                continue

            if isinstance(message, bytes):
                print(f"[Hermes] Received {len(message)} bytes of audio.")
                await websocket.send(json.dumps({
                    "type": "status",
                    "message": "Processing audio..."
                }))

                loop = asyncio.get_event_loop()
                text = await loop.run_in_executor(None, transcribe_audio, message)
                print(f"[Hermes] Transcribed: '{text}'")

                if not text or len(text.strip()) < 2:
                    await websocket.send(json.dumps({
                        "type": "status",
                        "message": "Didn't catch that. Try again."
                    }))
                    mic_activated = False
                    continue

                await websocket.send(json.dumps({
                    "type": "transcription",
                    "text": text
                }))

                if in_conversation and (time.time() - last_interaction) > CONVERSATION_TIMEOUT:
                    in_conversation = False
                    print("[Hermes] Conversation timed out.")

                has_wake, command = detect_wake_word(text)

                if has_wake and command:
                    in_conversation = True
                    last_interaction = time.time()
                    await respond_to_command(websocket, command)

                elif has_wake and not command:
                    in_conversation = True
                    last_interaction = time.time()
                    reply = "Yes? How may I help you?"
                    await websocket.send(json.dumps({
                        "type": "response", "text": reply
                    }))
                    await websocket.send(json.dumps({"type": "tts_start"}))
                    audio = await generate_tts_complete(reply)
                    await websocket.send(audio)
                    await websocket.send(json.dumps({"type": "tts_end"}))

                elif mic_activated or in_conversation:
                    in_conversation = True
                    last_interaction = time.time()
                    await respond_to_command(websocket, text)

                else:
                    await websocket.send(json.dumps({
                        "type": "status",
                        "message": f"Heard: \"{text}\" — say 'Hermes' to activate."
                    }))

                mic_activated = False

    except websockets.exceptions.ConnectionClosed:
        print("[Hermes] Client disconnected.")


# ── HTTP Server ─────────────────────────────────────────────────

# ── API Cache ────────────────────────────────────────────────────
_api_cache = {}  # {endpoint: (timestamp, data)}
_API_CACHE_TTL = 60  # seconds


class UIHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(Path(__file__).parent / "ui"), **kwargs)

    def log_message(self, format, *args):
        pass

    # ── Helper methods ───────────────────────────────────────────

    def _send_json(self, data, status=200):
        """Send a JSON response."""
        body = json.dumps(data, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _get_cached(self, key):
        """Return cached data if fresh, else None."""
        if key in _api_cache:
            ts, data = _api_cache[key]
            if time.time() - ts < _API_CACHE_TTL:
                return data
        return None

    def _set_cached(self, key, data):
        """Store data in cache."""
        _api_cache[key] = (time.time(), data)

    # ── Route dispatch ───────────────────────────────────────────

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/calendar":
            self._handle_calendar()
        elif path == "/api/clients":
            self._handle_clients()
        elif path == "/api/tasks":
            self._handle_tasks()
        elif path == "/api/tokens":
            self._handle_tokens()
        elif path == "/api/briefing":
            self._handle_briefing()
        elif path.startswith("/api/"):
            self._send_json({"error": "Unknown API endpoint"}, 404)
        else:
            super().do_GET()

    # ── /api/calendar ────────────────────────────────────────────

    def _handle_calendar(self):
        cached = self._get_cached("calendar")
        if cached is not None:
            return self._send_json(cached)
        try:
            from datetime import date, timedelta
            today = date.today().isoformat()
            tomorrow = (date.today() + timedelta(days=1)).isoformat()
            result = subprocess.run(
                ["acal", "events", "list", "--from", today, "--to", tomorrow],
                capture_output=True, text=True, timeout=15
            )
            raw = json.loads(result.stdout) if result.stdout.strip() else {}
            # acal returns {"ok": true, "data": [...]}
            event_list = raw.get("data", raw) if isinstance(raw, dict) else raw
            events = []
            for ev in event_list:
                events.append({
                    "title": ev.get("title", ""),
                    "start": ev.get("start", ev.get("startDate", "")),
                    "end": ev.get("end", ev.get("endDate", "")),
                    "location": ev.get("location", ""),
                    "allDay": ev.get("allDay", ev.get("isAllDay", False)),
                })
            events.sort(key=lambda e: e.get("start", ""))
            self._set_cached("calendar", events)
            self._send_json(events)
        except Exception as e:
            print(f"[Hermes] /api/calendar error: {e}")
            self._send_json([])

    # ── /api/clients ─────────────────────────────────────────────

    def _handle_clients(self):
        cached = self._get_cached("clients")
        if cached is not None:
            return self._send_json(cached)
        try:
            fpath = os.path.join(HERMES_BASE, "dashboard", "dashboard_data.json")
            with open(fpath) as f:
                data = json.load(f)
            clients_raw = data.get("clients", [])
            clients = []
            for c in clients_raw:
                clients.append({
                    "client": c.get("client", ""),
                    "rag": c.get("rag", ""),
                    "status": c.get("status", ""),
                    "progress": c.get("progress", 0),
                    "open_tasks": c.get("open_tasks", 0),
                    "overdue_tasks": c.get("overdue_tasks", 0),
                    "arr": c.get("arr", ""),
                    "close_date": c.get("close_date", ""),
                })
            self._set_cached("clients", clients)
            self._send_json(clients)
        except Exception as e:
            print(f"[Hermes] /api/clients error: {e}")
            self._send_json([])

    # ── /api/tasks ───────────────────────────────────────────────

    def _handle_tasks(self):
        cached = self._get_cached("tasks")
        if cached is not None:
            return self._send_json(cached)
        try:
            all_tasks = []
            for list_name in ["Work items", "Tasks", "Personal", "Family"]:
                try:
                    result = subprocess.run(
                        ["remindctl", "list", list_name],
                        capture_output=True, text=True, timeout=15
                    )
                    if result.stdout.strip():
                        all_tasks.extend(
                            self._parse_reminders(result.stdout, list_name)
                        )
                except Exception:
                    pass
            # Filter incomplete, sort by due date
            incomplete = [t for t in all_tasks if not t.get("completed", False)]
            incomplete.sort(key=lambda t: t.get("due_date", "") or "9999-12-31")
            self._set_cached("tasks", incomplete)
            self._send_json(incomplete)
        except Exception as e:
            print(f"[Hermes] /api/tasks error: {e}")
            self._send_json([])

    def _parse_reminders(self, text, list_name):
        """Parse remindctl text output into task dicts.
        Format: [N] [x]/[ ] Title [ListName] — DateString [priority=level]
        """
        tasks = []
        for line in text.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            # Match: [N] [x] or [ ] followed by title
            m = re.match(r'\[(\d+)\]\s+\[([ xX])\]\s+(.+)', line)
            if not m:
                continue
            completed = m.group(2).lower() == 'x'
            rest = m.group(3)
            # Extract priority if present
            priority = 0
            pri_match = re.search(r'priority=(high|medium|low)', rest)
            if pri_match:
                priority = {"high": 3, "medium": 2, "low": 1}.get(pri_match.group(1), 0)
                rest = rest[:pri_match.start()].strip()
            # Split on " — " to get title and date
            parts = rest.split(' — ', 1)
            title_part = parts[0].strip()
            due_str = parts[1].strip() if len(parts) > 1 else ""
            # Remove [ListName] from title
            title_part = re.sub(r'\s*\[.*?\]\s*$', '', title_part)
            # Parse date string like "May 13, 2026 at 8:00 AM" or "no due date"
            due_date = ""
            if due_str and due_str != "no due date":
                try:
                    from datetime import datetime
                    # Handle unicode narrow no-break space
                    due_str_clean = due_str.replace('\u202f', ' ').replace('\xa0', ' ')
                    dt = datetime.strptime(due_str_clean, "%b %d, %Y at %I:%M %p")
                    due_date = dt.strftime("%Y-%m-%d %H:%M")
                except (ValueError, Exception):
                    due_date = due_str
            title = title_part.strip(" \t-|")
            if title:
                tasks.append({
                    "title": title,
                    "due_date": due_date,
                    "completed": completed,
                    "list": list_name,
                    "priority": priority,
                })
        return tasks

    # ── /api/tokens ──────────────────────────────────────────────

    def _handle_tokens(self):
        limit = 1_000_000
        used = token_usage.get("input", 0) + token_usage.get("output", 0)
        self._send_json({
            "used": used,
            "input_tokens": token_usage.get("input", 0),
            "output_tokens": token_usage.get("output", 0),
            "limit": limit,
            "percentage": round((used / limit) * 100, 2) if limit else 0,
        })

    # ── /api/briefing ────────────────────────────────────────────

    def _handle_briefing(self):
        cached = self._get_cached("briefing")
        if cached is not None:
            return self._send_json(cached)
        try:
            fpath = os.path.join(HERMES_BASE, "daily-briefing", "briefing_data.json")
            with open(fpath) as f:
                data = json.load(f)
            sections = data.get("sections", data)
            self._set_cached("briefing", sections)
            self._send_json(sections)
        except Exception as e:
            print(f"[Hermes] /api/briefing error: {e}")
            self._send_json({})

def run_http_server():
    server = HTTPServer((HOST, HTTP_PORT), UIHandler)
    print(f"[Hermes] Web UI: http://{HOST}:{HTTP_PORT}")
    server.serve_forever()


# ── Main ────────────────────────────────────────────────────────

def _enabled_module_names():
    """Get list of enabled module names for display."""
    return [name for name, conf in ENABLED_MODULES.items() if conf.get("enabled")]


async def main():
    enabled = _enabled_module_names()
    print("━" * 50)
    print("  HERMES Voice Assistant v4")
    print(f"  Wake word: '{WAKE_WORD}'")
    print(f"  Voice: {VOICE}")
    print(f"  User: {USER_NAME}")
    print(f"  Modules: {', '.join(enabled) if enabled else 'none'}")
    print("━" * 50)

    load_thread = threading.Thread(target=load_whisper, daemon=True)
    load_thread.start()

    http_thread = threading.Thread(target=run_http_server, daemon=True)
    http_thread.start()

    print(f"[Hermes] WebSocket server on ws://{HOST}:{WS_PORT}")
    async with websockets.serve(handle_client, HOST, WS_PORT, max_size=50_000_000):
        print(f"\n[Hermes] Ready. Open http://{HOST}:{HTTP_PORT} in your browser.\n")
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())

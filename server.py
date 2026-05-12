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
        tools.append('- "web_extract": Fetch and read a specific web page URL. Params: {"url": "https://..."}')

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
        tools.append('- "noteplan_read": Read a specific NotePlan note by file path or noteplan:// URL. Params: {"file": "Work/Note Name.txt"} — extract the filename from noteplan:// URLs')
        tools.append('- "noteplan_write": Create a new note in the Work folder. Params: {"filename": "Note Title.txt", "content": "note content here"}')
        tools.append('- "noteplan_append": Add content to an existing note. Params: {"filename": "Existing Note.txt", "content": "content to append"}')

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
        instructions.append('When they ask to create a note, write something down, make a dossier, or save notes, USE noteplan_write. Dossiers are just notes with "Dossier" in the filename.')
        instructions.append('When they ask to add to an existing note, append to a dossier, or update notes, USE noteplan_append. Look in conversation history for the exact filename if referenced.')

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
- {_gender_hint} {_name_usage}
- FOLLOW-UPS: The conversation history includes previous tool outputs (marked with [Tool: ...]). 
  When the user refers to something from a previous result (e.g., "read that one", "the podcast email", "tell me more about the first one"), 
  look at the previous tool output in the conversation to find the relevant ID, name, or reference.
  For emails: extract the email ID number from the previous email_list output and use email_read with that ID.
  For notes: extract the file path from previous noteplan_search output and use noteplan_read.
- NOTEPLAN URLs: When user pastes a noteplan:// URL, use noteplan_read with the full URL as the "file" param. The system will extract the filename automatically.
- WEB URLs: When user pastes or mentions a specific URL (https://...), use web_extract to fetch and read it. Use web_search for general queries.
- MULTI-STEP: When the user asks you to combine information (e.g., "read this note and add it to a dossier"), do the FIRST step. The user will confirm before you do the next step. Don't say you can't — just do the first part.
- CONTEXT: Always check conversation history. If the user says "that", "it", "the note", "those details" — they're referring to something from a previous message. Find it in history and use it."""


def build_response_prompt():
    """Build the response formatting prompt from config."""
    return f"""You are Hermes, a sophisticated British AI assistant. 
Given the tool output below, craft a concise spoken response (1-3 sentences).
Use British English. Never use asterisk actions. Only spoken words.
Be helpful and specific — summarise the key information from the tool output.
When listing emails, mention the subject and sender so the user can ask about a specific one.
When listing events, mention the time and title.
For noteplan_write or noteplan_append: Do NOT read back the content that was written. Simply say something brief like "Done, I've created the dossier" or "Added to the note." The file location will be shown separately in the UI.
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


def _process_uploaded_file(filename, content_b64, mime):
    """Process an uploaded file — extract text from images via OCR, read text files."""
    import base64
    try:
        raw_bytes = base64.b64decode(content_b64)
    except Exception as e:
        return f"Error decoding file: {e}"
    
    ext = Path(filename).suffix.lower()
    is_image = ext in ('.png', '.jpg', '.jpeg', '.heic', '.webp', '.gif', '.bmp') or mime.startswith('image/')
    
    if is_image:
        # Save to temp file and run OCR via macOS Vision framework
        tmp_path = Path(tempfile.mktemp(suffix=ext))
        tmp_path.write_bytes(raw_bytes)
        
        # Convert HEIC to PNG if needed
        if ext == '.heic':
            png_path = tmp_path.with_suffix('.png')
            run_local_command(f'sips -s format png "{tmp_path}" --out "{png_path}"')
            if png_path.exists():
                tmp_path.unlink()
                tmp_path = png_path
        
        # Use macOS Vision framework for OCR
        ocr_result = run_local_command(f'''python3 -c "
import subprocess, json
result = subprocess.run(
    ['shortcuts', 'run', 'OCR Image', '-i', '{tmp_path}'],
    capture_output=True, text=True, timeout=30
)
if result.stdout.strip():
    print(result.stdout.strip())
else:
    # Fallback: use macOS screencapture + vision
    import Quartz
    from Foundation import NSURL
    from Vision import VNRecognizeTextRequest, VNImageRequestHandler
    url = NSURL.fileURLWithPath_(str('{tmp_path}'))
    handler = VNImageRequestHandler.alloc().initWithURL_options_(url, None)
    request = VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(1)
    handler.performRequests_error_([request], None)
    results = request.results()
    if results:
        for obs in results:
            print(obs.topCandidates_(1)[0].string())
    else:
        print('[No text detected in image]')
"''', timeout=30)
        
        # If OCR fails, try simpler approach
        if not ocr_result or "Error" in ocr_result or "Traceback" in ocr_result:
            # Use tesseract if available
            ocr_result = _safe_tool(f'tesseract "{tmp_path}" stdout 2>/dev/null', "tesseract", timeout=15)
            if "not installed" in ocr_result:
                # Last resort: describe what we can see from the filename
                ocr_result = f"[Image uploaded: {filename}. OCR not available. Please install tesseract: brew install tesseract]"
        
        try:
            tmp_path.unlink()
        except Exception:
            pass
        
        return f"[Image: {filename}]\n{ocr_result}"
    
    else:
        # Text-based file — decode and read
        try:
            text = raw_bytes.decode('utf-8', errors='ignore')
            if len(text) > 3000:
                text = text[:3000] + "\n... (truncated)"
            return f"[File: {filename}]\n{text}"
        except Exception as e:
            return f"Error reading file: {e}"


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


def noteplan_write(filename, content, append=False):
    """Create or append to a note in the NotePlan Work folder."""
    if not NOTEPLAN_PATH:
        return "NotePlan path not configured. Please run the setup wizard."
    np_path = Path(NOTEPLAN_PATH).expanduser()
    work_path = np_path / "Work"
    if not work_path.exists():
        work_path = np_path  # Fall back to root notes path
    
    # Sanitize filename
    safe_name = filename.strip()
    if not safe_name.endswith(('.txt', '.md')):
        safe_name += '.txt'
    
    target = work_path / safe_name
    
    # Security check
    try:
        target.resolve().relative_to(np_path.resolve())
    except ValueError:
        return "Access denied: path is outside the NotePlan directory."
    
    try:
        if append and target.exists():
            existing = target.read_text(encoding="utf-8", errors="ignore")
            # Add separator + new content
            new_content = existing.rstrip() + "\n\n---\n\n" + content
            target.write_text(new_content, encoding="utf-8")
            return f"Appended to note: {safe_name}"
        else:
            target.write_text(content, encoding="utf-8")
            return f"Created note: {safe_name}"
    except Exception as e:
        return f"Error writing note: {e}"


def noteplan_append(filename, content):
    """Append content to an existing note (convenience wrapper)."""
    return noteplan_write(filename, content, append=True)


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
        if not query:
            return "Missing search query."
        # Use ddgr if available, otherwise use Python + DuckDuckGo lite
        result = _safe_tool(f'ddgr --json -n 5 {json.dumps(query)} 2>/dev/null', "ddgr", timeout=15)
        if "not installed" in result or "not found" in result.lower() or not result.strip():
            # Fallback: use Python urllib to fetch DuckDuckGo lite
            result = run_local_command(
                f'''python3 -c "
import urllib.request, urllib.parse, re, html
q = urllib.parse.quote({json.dumps(query)})
url = 'https://lite.duckduckgo.com/lite/?q=' + q
req = urllib.request.Request(url, headers={{'User-Agent': 'Mozilla/5.0'}})
data = urllib.request.urlopen(req, timeout=10).read().decode()
results = re.findall(r'<a[^>]+class=\"result-link\"[^>]*href=\"([^\"]+)\"[^>]*>([^<]+)', data)
if not results:
    results = re.findall(r'<a[^>]+href=\"(https?://[^\"]+)\"[^>]*>\\s*<b>([^<]*)</b>', data)
for url, title in results[:5]:
    print(f'• {{html.unescape(title.strip())}}: {{url}}')
if not results:
    print('No results found.')
"''', timeout=15)
        return result
    
    # ── Web extract (fetch a specific URL) ──
    elif tool == "web_extract":
        url = params.get("url", "")
        if not url:
            return "Missing URL to extract."
        # Use curl to fetch page content, strip HTML
        result = run_local_command(
            f'''python3 -c "
import urllib.request, re, html
req = urllib.request.Request({json.dumps(url)}, headers={{'User-Agent': 'Mozilla/5.0'}})
data = urllib.request.urlopen(req, timeout=15).read().decode(errors='ignore')
text = re.sub(r'<script[^>]*>.*?</script>', '', data, flags=re.DOTALL)
text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
text = re.sub(r'<[^>]+>', ' ', text)
text = re.sub(r'\\s+', ' ', text).strip()
print(text[:3000])
"''', timeout=20)
        return result

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
        # Handle noteplan:// URLs — extract filename param
        if "noteplan://" in file_path:
            from urllib.parse import urlparse, parse_qs, unquote
            try:
                parsed = urlparse(file_path)
                qs = parse_qs(parsed.query)
                file_path = unquote(qs.get("filename", [file_path])[0])
            except Exception:
                pass
        # URL-decode any %20 etc in the path
        from urllib.parse import unquote
        file_path = unquote(file_path)
        return noteplan_read(file_path)

    elif tool == "noteplan_write":
        if not ENABLED_MODULES.get("noteplan", {}).get("enabled"):
            return "NotePlan module is not enabled."
        filename = params.get("filename", "")
        content = params.get("content", "")
        if not filename or not content:
            return "Missing filename or content for the note."
        return noteplan_write(filename, content, append=False)

    elif tool == "noteplan_append":
        if not ENABLED_MODULES.get("noteplan", {}).get("enabled"):
            return "NotePlan module is not enabled."
        filename = params.get("filename", "")
        content = params.get("content", "")
        if not filename or not content:
            return "Missing filename or content to append."
        return noteplan_append(filename, content)

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
    if len(conversation_history) > 40:
        conversation_history = conversation_history[-40:]

    # Step 1: Classify intent — send generous history for multi-turn context
    # Each tool call produces ~3 messages (user + tool_output + reply), so 20 messages = ~6-7 exchanges
    classify_messages = [
        {"role": "system", "content": CLASSIFIER_PROMPT},
    ] + conversation_history[-20:]

    raw = await call_llm(classify_messages, max_tokens=500)
    if not raw:
        reply = "I'm afraid I can't reach my thinking engines at the moment."
        conversation_history.append({"role": "assistant", "content": reply})
        return reply, None

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
        return reply, None

    tool = action.get("tool", "chat")
    params = action.get("params", {})

    # Step 2: Execute tool
    if tool == "chat":
        reply = params.get("reply", "How may I help you?")
        conversation_history.append({"role": "assistant", "content": reply})
        return reply, None

    # Run tool in thread pool (blocking I/O)
    loop = asyncio.get_event_loop()
    tool_output = await loop.run_in_executor(None, execute_tool, tool, params)
    print(f"[Hermes] Tool output ({tool}): {tool_output[:200]}")

    # Store tool output in conversation history so follow-ups have context
    tool_context = f"[Tool: {tool}]\n{tool_output[:2000]}"
    conversation_history.append({"role": "assistant", "content": tool_context})

    # Build metadata for noteplan write/append (clickable link in UI)
    metadata = None
    if tool in ("noteplan_write", "noteplan_append") and ("Created note:" in tool_output or "Appended to note:" in tool_output):
        filename = params.get("filename", "").strip()
        if not filename.endswith(('.txt', '.md')):
            filename += '.txt'
        np_path = Path(NOTEPLAN_PATH).expanduser() if NOTEPLAN_PATH else None
        work_path = np_path / "Work" if np_path and (np_path / "Work").exists() else np_path
        if work_path:
            full_path = work_path / filename
            # noteplan:// URL scheme opens notes in NotePlan
            np_url = f"noteplan://x-callback-url/openNote?filename={filename}"
            metadata = {
                "type": "noteplan_link",
                "filename": filename,
                "path": str(full_path),
                "url": np_url,
            }

    # Step 3: Format tool output into a spoken response
    format_messages = [
        {"role": "system", "content": RESPONSE_PROMPT},
        {"role": "user", "content": f"User asked: {user_message}\n\nTool used: {tool}\nTool output:\n{tool_output[:1500]}"},
    ]

    reply = await call_llm(format_messages, max_tokens=250)
    if not reply:
        reply = f"Here's what I found: {tool_output[:200]}"

    # Also store the spoken reply so conversation flows naturally
    conversation_history.append({"role": "assistant", "content": reply})
    return reply, metadata


# ── Command Handler ─────────────────────────────────────────────

async def respond_to_command(websocket, command):
    """Handle a command: classify → execute tool → format → TTS."""
    t0 = time.time()

    reply, metadata = await classify_and_execute(command)
    t1 = time.time()
    print(f'[Hermes] Total LLM+Tool: {t1-t0:.2f}s → "{reply}"')

    # Send text IMMEDIATELY
    await websocket.send(json.dumps({
        "type": "response",
        "text": reply
    }))

    # Send noteplan link if a note was created/updated
    if metadata and metadata.get("type") == "noteplan_link":
        await websocket.send(json.dumps({
            "type": "noteplan_link",
            "filename": metadata["filename"],
            "path": metadata["path"],
            "url": metadata["url"],
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

                elif data.get("type") == "file_upload":
                    filename = data.get("name", "unknown")
                    content_b64 = data.get("content", "")
                    mime = data.get("mime", "")
                    print(f"[Hermes] File upload: {filename} ({mime}, {len(content_b64)} chars b64)")
                    
                    in_conversation = True
                    last_interaction = time.time()
                    
                    await websocket.send(json.dumps({
                        "type": "status",
                        "message": f"Analysing {filename}..."
                    }))
                    
                    # Process the file
                    loop = asyncio.get_event_loop()
                    file_analysis = await loop.run_in_executor(
                        None, _process_uploaded_file, filename, content_b64, mime
                    )
                    
                    # Send to LLM as a command with file context
                    command = f"I just uploaded a file called '{filename}'. Here is its content:\n\n{file_analysis[:3000]}\n\nPlease analyse this. If there are any dates, meetings, events, deadlines, or appointments mentioned, point them out so I can add them to my calendar. Also summarise the key information."
                    await respond_to_command(websocket, command)
                    
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
_SYSTEM_CACHE_TTL = 5  # seconds — system stats refresh frequently


def _get_system_stats():
    """Gather real-time system stats using macOS shell commands."""
    import platform
    stats = {}

    os_name = "macOS" if platform.system() == "Darwin" else platform.system()
    stats["os_name"] = os_name

    # ── CPU usage via ps ──
    try:
        r = subprocess.run(
            ["ps", "-A", "-o", "%cpu"], capture_output=True, text=True, timeout=5
        )
        lines = r.stdout.strip().splitlines()[1:]  # skip header
        total = sum(float(l.strip()) for l in lines if l.strip())
        # Normalize by number of CPUs
        try:
            ncpu = int(subprocess.run(
                ["sysctl", "-n", "hw.logicalcpu"], capture_output=True, text=True, timeout=3
            ).stdout.strip())
        except Exception:
            ncpu = 1
        stats["cpu_percent"] = round(min(total / ncpu, 100.0), 1)
    except Exception:
        stats["cpu_percent"] = None

    # ── RAM via vm_stat + sysctl ──
    try:
        mem_total_bytes = int(subprocess.run(
            ["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=3
        ).stdout.strip())
        ram_total_gb = mem_total_bytes / (1024 ** 3)

        vm = subprocess.run(
            ["vm_stat"], capture_output=True, text=True, timeout=3
        ).stdout
        # Parse page size
        page_size = 4096
        ps_match = re.search(r'page size of (\d+) bytes', vm)
        if ps_match:
            page_size = int(ps_match.group(1))
        # Parse page counts
        def _vm_val(key):
            m = re.search(rf'{key}:\s+(\d+)', vm)
            return int(m.group(1)) if m else 0
        free = _vm_val("Pages free")
        inactive = _vm_val("Pages inactive")
        speculative = _vm_val("Pages speculative")
        # "used" = total - (free + inactive + speculative) pages
        free_bytes = (free + inactive + speculative) * page_size
        used_bytes = mem_total_bytes - free_bytes
        ram_used_gb = max(used_bytes, 0) / (1024 ** 3)
        ram_percent = round((ram_used_gb / ram_total_gb) * 100, 1) if ram_total_gb else 0

        stats["ram_total_gb"] = round(ram_total_gb, 2)
        stats["ram_used_gb"] = round(ram_used_gb, 2)
        stats["ram_percent"] = ram_percent
    except Exception:
        stats["ram_total_gb"] = None
        stats["ram_used_gb"] = None
        stats["ram_percent"] = None

    # ── Disk usage via df ──
    try:
        r = subprocess.run(
            ["df", "-k", "/"], capture_output=True, text=True, timeout=5
        )
        lines = r.stdout.strip().splitlines()
        if len(lines) >= 2:
            parts = lines[1].split()
            capacity = parts[4].replace("%", "")
            stats["disk_usage_percent"] = int(capacity)
        else:
            stats["disk_usage_percent"] = None
    except Exception:
        stats["disk_usage_percent"] = None

    # ── Disk read rate (approximate snapshot) ──
    try:
        # Use iostat for a 1-second sample
        r = subprocess.run(
            ["iostat", "-d", "-c", "2", "-w", "1"], capture_output=True, text=True, timeout=5
        )
        lines = r.stdout.strip().splitlines()
        # Last line has the 1-second sample
        if len(lines) >= 2:
            last = lines[-1].split()
            # iostat columns: KB/t, tps, MB/s — take MB/s and convert to KB/s
            if len(last) >= 3:
                mbs = float(last[2])
                stats["disk_read_rate"] = round(mbs * 1024, 1)
            else:
                stats["disk_read_rate"] = None
        else:
            stats["disk_read_rate"] = None
    except Exception:
        stats["disk_read_rate"] = None

    # ── GPU usage ──
    try:
        if os_name == "macOS":
            r = subprocess.run(
                ["ioreg", "-r", "-d", "1", "-c", "IOAccelerator"],
                capture_output=True, text=True, timeout=5
            )
            m = re.search(r'"Device Utilization %"\s*=\s*(\d+)', r.stdout)
            stats["gpu_percent"] = int(m.group(1)) if m else None
        else:
            stats["gpu_percent"] = None
    except Exception:
        stats["gpu_percent"] = None

    # ── CPU temperature ──
    try:
        r = subprocess.run(
            ["osx-cpu-temp"], capture_output=True, text=True, timeout=3
        )
        if r.returncode == 0 and r.stdout.strip():
            m = re.search(r'([\d.]+)', r.stdout)
            stats["cpu_temp"] = float(m.group(1)) if m else None
        else:
            stats["cpu_temp"] = None
    except Exception:
        stats["cpu_temp"] = None

    # ── Uptime ──
    try:
        r = subprocess.run(
            ["uptime"], capture_output=True, text=True, timeout=3
        )
        raw = r.stdout.strip()
        # Extract "up X days, HH:MM" or similar
        m = re.search(r'up\s+(.+?),\s+\d+\s+user', raw)
        stats["uptime"] = m.group(1).strip() if m else raw
    except Exception:
        stats["uptime"] = None

    # ── Process count ──
    try:
        r = subprocess.run(
            "ps aux | wc -l", shell=True, capture_output=True, text=True, timeout=5
        )
        count = int(r.stdout.strip()) - 1  # subtract header line
        stats["process_count"] = max(count, 0)
    except Exception:
        stats["process_count"] = None

    return stats


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
        elif path == "/api/system":
            self._handle_system()
        elif path.startswith("/api/"):
            self._send_json({"error": "Unknown API endpoint"}, 404)
        else:
            super().do_GET()

    # ── /api/calendar ────────────────────────────────────────────

    def _handle_calendar(self):
        # Support ?date=YYYY-MM-DD query param for viewing other days
        from datetime import date as date_cls, timedelta
        from urllib.parse import urlparse, parse_qs
        query_params = parse_qs(urlparse(self.path).query)
        requested_date = query_params.get("date", [None])[0]
        
        if requested_date:
            try:
                target_date = date_cls.fromisoformat(requested_date)
            except ValueError:
                target_date = date_cls.today()
        else:
            target_date = date_cls.today()
        
        cache_key = f"calendar_{target_date.isoformat()}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return self._send_json(cached)
        try:
            day_start = target_date.isoformat()
            day_end = (target_date + timedelta(days=1)).isoformat()
            result = subprocess.run(
                ["acal", "events", "list", "--from", day_start, "--to", day_end],
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
                    "calendarId": ev.get("calendarId", ""),
                })
            events.sort(key=lambda e: e.get("start", ""))
            self._set_cached(cache_key, events)
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

    # ── /api/system ───────────────────────────────────────────────

    def _handle_system(self):
        # Use shorter TTL for system stats (5 seconds)
        cached = self._get_cached("system")
        if cached is not None:
            # Check against the shorter TTL
            ts, _ = _api_cache.get("system", (0, None))
            if time.time() - ts < _SYSTEM_CACHE_TTL:
                return self._send_json(cached)
        try:
            data = _get_system_stats()
            _api_cache["system"] = (time.time(), data)
            self._send_json(data)
        except Exception as e:
            print(f"[Hermes] /api/system error: {e}")
            self._send_json({"error": str(e)}, 500)

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

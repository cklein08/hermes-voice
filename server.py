"""
HERMES Voice Assistant — Backend Server (v3 — full tool access)
British-voiced AI assistant with wake word detection, Whisper STT, Edge TTS.
Routes commands through local tools: email, calendar, reminders, web search, terminal.
"""

import asyncio
import json
import os
import re
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler

import numpy as np
import edge_tts
import whisper
import websockets

# ── Config ──────────────────────────────────────────────────────
WAKE_WORD = "hermes"
BRITISH_VOICE = "en-GB-RyanNeural"
WHISPER_MODEL = "base"
HOST = "127.0.0.1"
WS_PORT = 8765
HTTP_PORT = 8766
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")

CLASSIFIER_PROMPT = """You are Hermes, a British AI assistant with access to local tools on a macOS system.
Analyse the user's request and respond with a JSON object indicating the action to take.

Available tools:
- "email_list": List recent emails (inbox). No params needed.
- "email_send": Send an email. Params: {"to": "address", "subject": "...", "body": "..."}
- "email_search": Search emails by keyword. Params: {"query": "search terms"}
- "email_read": Read a specific email by ID. Params: {"id": "email_id_number"}
- "calendar_today": Show today's calendar events. No params needed.
- "calendar_list": Show upcoming events for N days. Params: {"days": number}
- "reminder_list": List all reminders across all lists. No params needed.
- "reminder_add": Add a reminder. Params: {"title": "...", "list": "optional list name"}
- "web_search": Search the web. Params: {"query": "search terms"}
- "terminal": Run a macOS shell command. Params: {"command": "..."}
- "open_dashboard": Open the client engagement dashboard in browser. No params needed.
- "open_briefing": Open the daily briefing dashboard in browser. No params needed.
- "refresh_dashboard": Refresh/regenerate the client dashboard data. No params needed.
- "refresh_briefing": Refresh/regenerate the daily briefing data. No params needed.
- "chat": Just a conversational response, no tool needed. Params: {"reply": "your response"}

The user's email is carolyn.klein08@gmail.com. Her work email is cklein@adobe.com.
When she says "send email" or "check my email" or "do I have any emails", USE the email tools — do NOT say you can't.
When she asks about her schedule/meetings/calendar, USE the calendar tools.
When she asks to remind her of something, USE reminder_add.
When she says "dashboard", "client dashboard", "engagement dashboard" → use open_dashboard.
When she says "briefing", "daily brief", "daily briefing" → use open_briefing.
When she says "refresh dashboard" or "update dashboard" → use refresh_dashboard.
When she says "refresh briefing" or "update briefing" → use refresh_briefing.

IMPORTANT: 
- Respond ONLY with a JSON object: {"tool": "tool_name", "params": {...}}
- For "chat", include your full spoken response in params.reply
- Never use asterisk actions. Write only spoken words.
- Be concise (1-3 sentences) for chat responses.
- Use British English.
- For email, calendar, reminders — prefer using the tools over saying you can't.
- The user is Carolyn, a woman. Never call her "sir". Use "Carolyn", "ma'am", or "Ms Klein" sparingly — only at conversation start, mid-point, or sign-off. Most replies need no name at all."""

RESPONSE_PROMPT = """You are Hermes, a sophisticated British AI assistant. 
Given the tool output below, craft a concise spoken response (1-3 sentences).
Use British English. Never use asterisk actions. Only spoken words.
Be helpful and specific — summarise the key information from the tool output.
The user is Carolyn, a woman. Never call her "sir". Don't use her name in every reply — only at start or end of conversation."""

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
    communicate = edge_tts.Communicate(text, BRITISH_VOICE, rate="+5%", pitch="+0Hz")
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
    except Exception as e:
        return f"Error: {e}"


def execute_tool(tool, params):
    """Execute a local tool and return the output."""
    print(f"[Hermes] Executing tool: {tool} with params: {params}")
    
    if tool == "email_list":
        return run_local_command("himalaya envelope list --account gmail -s 10")
    
    elif tool == "email_send":
        to = params.get("to", "")
        subject = params.get("subject", "")
        body = params.get("body", "")
        if not to or not subject:
            return "Missing recipient or subject for email."
        # Use himalaya template to send
        tpl = f"From: carolyn.klein08@gmail.com\nTo: {to}\nSubject: {subject}\n\n{body}"
        cmd = f'echo {json.dumps(tpl)} | himalaya message send --account gmail'
        return run_local_command(cmd)
    
    elif tool == "email_search":
        query = params.get("query", "")
        return run_local_command(f'himalaya envelope list --account gmail -s 10 -q {json.dumps(query)}')
    
    elif tool == "email_read":
        id_num = params.get("id", "")
        if not id_num:
            return "Missing email ID."
        return run_local_command(f'himalaya message read --account gmail {id_num}')
    
    elif tool == "calendar_today":
        today = time.strftime("%Y-%m-%d")
        tomorrow = time.strftime("%Y-%m-%d", time.localtime(time.time() + 86400))
        return run_local_command(f'acal events list --from {today} --to {tomorrow}')
    
    elif tool == "calendar_list":
        days = params.get("days", 3)
        today = time.strftime("%Y-%m-%d")
        end = time.strftime("%Y-%m-%d", time.localtime(time.time() + 86400 * days))
        return run_local_command(f'acal events list --from {today} --to {end}')
    
    elif tool == "reminder_list":
        return run_local_command("remindctl list")
    
    elif tool == "reminder_add":
        title = params.get("title", "")
        list_name = params.get("list", "Reminders")
        if not title:
            return "Missing reminder title."
        cmd = f'remindctl add --list {json.dumps(list_name)} {json.dumps(title)}'
        return run_local_command(cmd)
    
    elif tool == "web_search":
        query = params.get("query", "")
        # Use ddgr (DuckDuckGo) or curl
        return run_local_command(f'curl -s "https://html.duckduckgo.com/html/?q={query}" | grep -oP "(?<=class=\"result__a\" href=\").*?(?=\")" | head -5 2>/dev/null || echo "Search completed for: {query}"')
    
    elif tool == "open_dashboard":
        run_local_command("open /Users/cklein/.hermes/dashboard/index.html")
        return "Client engagement dashboard opened in your browser."
    
    elif tool == "open_briefing":
        run_local_command("open /Users/cklein/.hermes/daily-briefing/index.html")
        return "Daily briefing dashboard opened in your browser."
    
    elif tool == "refresh_dashboard":
        output = run_local_command("bash /Users/cklein/.hermes/scripts/dashboard/refresh.sh", timeout=60)
        run_local_command("open /Users/cklein/.hermes/dashboard/index.html")
        return f"Dashboard refreshed and opened. {output}"
    
    elif tool == "refresh_briefing":
        output = run_local_command("cd /Users/cklein/.hermes/scripts/daily-briefing && python3 collect_briefing.py && python3 generate_briefing.py", timeout=60)
        run_local_command("open /Users/cklein/.hermes/daily-briefing/index.html")
        return f"Daily briefing regenerated and opened. {output}"
    
    elif tool == "terminal":
        command = params.get("command", "")
        if not command:
            return "No command specified."
        dangerous = ["rm -rf /", "mkfs", "dd if=", "> /dev/"]
        for d in dangerous:
            if d in command:
                return "I'm afraid I can't execute that command. Safety first."
        return run_local_command(command)
    
    elif tool == "chat":
        return params.get("reply", "I'm here. How can I help?")
    
    else:
        return f"Unknown tool: {tool}"


# ── LLM Calls ──────────────────────────────────────────────────

async def call_llm(messages, max_tokens=300):
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
    
    raw = await call_llm(classify_messages, max_tokens=300)
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
    
    reply = await call_llm(format_messages, max_tokens=250)
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
    print(f"[Hermes] Total LLM+Tool: {t1-t0:.2f}s → \"{reply}\"")
    
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

class UIHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(Path(__file__).parent / "ui"), **kwargs)
    def log_message(self, format, *args):
        pass

def run_http_server():
    server = HTTPServer((HOST, HTTP_PORT), UIHandler)
    print(f"[Hermes] Web UI: http://{HOST}:{HTTP_PORT}")
    server.serve_forever()


# ── Main ────────────────────────────────────────────────────────

async def main():
    print("━" * 50)
    print("  HERMES Voice Assistant v3")
    print("  Wake word: 'Hermes'")
    print("  Voice: British (Ryan Neural)")
    print("  Tools: email, calendar, reminders, terminal")
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

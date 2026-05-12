#!/usr/bin/env python3
"""
HERMES Voice Assistant — Interactive Setup Wizard
Beautiful terminal-based setup for first-time configuration.
"""

import asyncio
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time

# ── ANSI Colors ──────────────────────────────────────────────────────────────

class C:
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    DIM     = "\033[2m"
    ITALIC  = "\033[3m"
    UNDER   = "\033[4m"
    # Foreground
    RED     = "\033[31m"
    GREEN   = "\033[32m"
    YELLOW  = "\033[33m"
    BLUE    = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN    = "\033[36m"
    WHITE   = "\033[37m"
    GRAY    = "\033[90m"
    # Bright
    BRED    = "\033[91m"
    BGREEN  = "\033[92m"
    BYELLOW = "\033[93m"
    BBLUE   = "\033[94m"
    BMAGENTA= "\033[95m"
    BCYAN   = "\033[96m"
    BWHITE  = "\033[97m"
    # Background
    BG_BLUE = "\033[44m"
    BG_CYAN = "\033[46m"

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# ── Helpers ──────────────────────────────────────────────────────────────────

def clear():
    os.system("cls" if os.name == "nt" else "clear")

def banner():
    print()
    print(f"  {C.BBLUE}{C.BOLD}╔══════════════════════════════════════════════════╗{C.RESET}")
    print(f"  {C.BBLUE}{C.BOLD}║{C.RESET}                                                  {C.BBLUE}{C.BOLD}║{C.RESET}")
    print(f"  {C.BBLUE}{C.BOLD}║{C.RESET}   {C.BCYAN}{C.BOLD}⚡  H E R M E S{C.RESET}   {C.DIM}Voice Assistant{C.RESET}              {C.BBLUE}{C.BOLD}║{C.RESET}")
    print(f"  {C.BBLUE}{C.BOLD}║{C.RESET}                                                  {C.BBLUE}{C.BOLD}║{C.RESET}")
    print(f"  {C.BBLUE}{C.BOLD}║{C.RESET}   {C.DIM}Your intelligent British AI companion{C.RESET}          {C.BBLUE}{C.BOLD}║{C.RESET}")
    print(f"  {C.BBLUE}{C.BOLD}║{C.RESET}                                                  {C.BBLUE}{C.BOLD}║{C.RESET}")
    print(f"  {C.BBLUE}{C.BOLD}╚══════════════════════════════════════════════════╝{C.RESET}")
    print()

def step_header(num, total, title, emoji=""):
    width = 50
    print()
    print(f"  {C.GRAY}{'─' * width}{C.RESET}")
    print(f"  {emoji}  {C.BOLD}{C.BCYAN}Step {num} of {total}{C.RESET}  {C.BOLD}{title}{C.RESET}")
    print(f"  {C.GRAY}{'─' * width}{C.RESET}")
    print()

def prompt(text, default=None):
    if default:
        suffix = f" {C.DIM}[{default}]{C.RESET}: "
    else:
        suffix = f": "
    result = input(f"  {C.BWHITE}{text}{suffix}{C.RESET}").strip()
    return result if result else default

def prompt_yn(text, default=True):
    hint = "Y/n" if default else "y/N"
    result = input(f"  {C.BWHITE}{text} {C.DIM}[{hint}]{C.RESET}: ").strip().lower()
    if not result:
        return default
    return result in ("y", "yes")

def prompt_choice(text, options, default=None):
    """Display numbered options and return the selected value."""
    print(f"  {C.BWHITE}{text}{C.RESET}")
    print()
    for i, (value, label) in enumerate(options, 1):
        marker = f" {C.BGREEN}← default{C.RESET}" if value == default else ""
        print(f"    {C.BCYAN}{i}{C.RESET}) {label}{marker}")
    print()
    while True:
        choice = input(f"  {C.BWHITE}Your choice{C.RESET} {C.DIM}[1-{len(options)}]{C.RESET}: ").strip()
        if not choice and default:
            for i, (v, _) in enumerate(options):
                if v == default:
                    return v
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(options):
                return options[idx][0]
        except (ValueError, IndexError):
            pass
        print(f"  {C.RED}Please enter a number between 1 and {len(options)}{C.RESET}")

def success(text):
    print(f"  {C.BGREEN}✓{C.RESET} {text}")

def info(text):
    print(f"  {C.BCYAN}ℹ{C.RESET} {text}")

def warn(text):
    print(f"  {C.BYELLOW}⚠{C.RESET} {text}")

def error(text):
    print(f"  {C.BRED}✗{C.RESET} {text}")

def is_command_available(cmd):
    return shutil.which(cmd) is not None

def offer_brew_install(tool_name, brew_pkg=None):
    """Offer to install a tool via Homebrew. Returns True if installed or already present."""
    if is_command_available(tool_name):
        success(f"{tool_name} is already installed")
        return True

    warn(f"{tool_name} is not installed on your system.")
    if not is_command_available("brew"):
        error("Homebrew is not installed — please install it first: https://brew.sh")
        return False

    pkg = brew_pkg or tool_name
    if prompt_yn(f"Install {tool_name} via Homebrew? (brew install {pkg})"):
        print(f"  {C.DIM}Installing {tool_name}...{C.RESET}")
        try:
            subprocess.run(["brew", "install", pkg], check=True,
                           capture_output=True, text=True, timeout=300)
            success(f"{tool_name} installed successfully!")
            return True
        except subprocess.CalledProcessError as e:
            error(f"Installation failed: {e.stderr[:200] if e.stderr else 'unknown error'}")
            return False
        except subprocess.TimeoutExpired:
            error("Installation timed out")
            return False
    else:
        info(f"Skipping {tool_name} — you can install it later.")
        return False


# ── Step Functions ───────────────────────────────────────────────────────────

def step_welcome():
    clear()
    banner()
    print(f"  {C.BOLD}Welcome to the HERMES setup wizard!{C.RESET}")
    print()
    print(f"  This will take about {C.BCYAN}2-3 minutes{C.RESET} and will configure:")
    print()
    print(f"    🗣️  Your preferred voice")
    print(f"    🔑  API connection")
    print(f"    📧  Email integration {C.DIM}(optional){C.RESET}")
    print(f"    📅  Calendar & reminders {C.DIM}(optional){C.RESET}")
    print(f"    🎯  Feature presets")
    print()
    print(f"  {C.DIM}You can re-run this wizard anytime with: python setup_wizard.py{C.RESET}")
    print()
    input(f"  {C.BOLD}Press Enter to begin...{C.RESET}")


def step_name():
    step_header(1, 8, "What should I call you?", "👤")
    print(f"  {C.DIM}HERMES likes to be polite — let's get your name right.{C.RESET}")
    print()

    name = None
    while not name:
        name = prompt("Your full name")
        if not name:
            warn("Please enter your name so HERMES knows who it's talking to.")

    first_name = name.split()[0]
    print()
    style = prompt_choice(
        "How would you like HERMES to address you?",
        [
            ("first_name", f"By first name — \"{first_name}\""),
            ("formal", f"Formally — \"Mr/Ms {name.split()[-1]}\""),
            ("none", "No name — just get to the point"),
        ],
        default="first_name"
    )

    success(f"Got it! I'll remember you as {C.BOLD}{name}{C.RESET}")
    return name, style


def step_api_key():
    step_header(2, 8, "Connect to OpenRouter", "🔑")
    print(f"  HERMES uses {C.BOLD}OpenRouter{C.RESET} to access AI models.")
    print(f"  You'll need a free API key from:")
    print()
    print(f"    {C.UNDER}{C.BBLUE}https://openrouter.ai/keys{C.RESET}")
    print()
    print(f"  {C.DIM}(Copy your key, then paste it here — it won't be shown){C.RESET}")
    print()

    api_key = None
    while True:
        import getpass
        try:
            api_key = getpass.getpass(f"  {C.BWHITE}API Key: {C.RESET}").strip()
        except EOFError:
            api_key = prompt("API Key (will be visible)")

        if not api_key:
            warn("An API key is required for HERMES to work.")
            continue

        if not api_key.startswith("sk-"):
            warn("That doesn't look like an OpenRouter key (should start with 'sk-').")
            if not prompt_yn("Use it anyway?", default=False):
                continue

        # Validate the key
        print(f"  {C.DIM}Validating your API key...{C.RESET}", end="", flush=True)
        valid = validate_api_key(api_key)
        if valid:
            print(f"\r  {' ' * 40}\r", end="")
            success("API key is valid and working!")
            break
        else:
            print(f"\r  {' ' * 40}\r", end="")
            error("Could not validate this key — the API returned an error.")
            if prompt_yn("Try a different key?", default=True):
                continue
            else:
                warn("Proceeding with unvalidated key — you can fix this in config.json later.")
                break

    return api_key


def validate_api_key(key):
    """Validate OpenRouter API key with a minimal test call."""
    try:
        import aiohttp

        async def _check():
            headers = {
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": "openrouter/auto",
                "messages": [{"role": "user", "content": "Say ok"}],
                "max_tokens": 5,
            }
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        "https://openrouter.ai/api/v1/chat/completions",
                        headers=headers,
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=15),
                    ) as resp:
                        return resp.status == 200
            except Exception:
                return False

        return asyncio.run(_check())
    except ImportError:
        # aiohttp not available — try urllib
        try:
            import urllib.request
            import urllib.error
            req = urllib.request.Request(
                "https://openrouter.ai/api/v1/models",
                headers={"Authorization": f"Bearer {key}"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status == 200
        except Exception:
            return False


def step_voice():
    step_header(3, 8, "Choose your voice", "🗣️")
    print(f"  {C.DIM}HERMES speaks with a British accent. Pick the voice you like best.{C.RESET}")
    print()

    voices = [
        ("en-GB-RyanNeural",   "Ryan    — Male, warm & professional"),
        ("en-GB-ThomasNeural", "Thomas  — Male, calm & measured"),
        ("en-GB-SoniaNeural",  "Sonia   — Female, clear & confident"),
        ("en-GB-LibbyNeural",  "Libby   — Female, friendly & bright"),
        ("en-GB-MaisieNeural", "Maisie  — Female, young & energetic"),
    ]

    voice = prompt_choice("Which voice would you like?", voices, default="en-GB-RyanNeural")
    voice_label = dict(voices)[voice].split("—")[0].strip()

    # Offer to preview
    print()
    if prompt_yn(f"Would you like to hear a sample of {voice_label}'s voice?"):
        play_voice_sample(voice, voice_label)

    success(f"Voice set to {C.BOLD}{voice_label}{C.RESET} ({voice})")
    return voice


def play_voice_sample(voice_id, label):
    """Play a short TTS sample using edge-tts."""
    sample_text = "Hello! I'm HERMES, your personal voice assistant. How may I help you today?"
    tmp_file = os.path.join(tempfile.gettempdir(), "hermes_voice_sample.mp3")

    print(f"  {C.DIM}Generating voice sample...{C.RESET}", end="", flush=True)
    try:
        result = subprocess.run(
            [sys.executable, "-m", "edge_tts",
             "--voice", voice_id,
             "--text", sample_text,
             "--write-media", tmp_file],
            capture_output=True, text=True, timeout=20,
        )
        if result.returncode != 0:
            print(f"\r  {' ' * 50}\r", end="")
            warn("Could not generate voice sample. Skipping preview.")
            return
    except (subprocess.TimeoutExpired, FileNotFoundError):
        print(f"\r  {' ' * 50}\r", end="")
        warn("Voice preview not available (edge-tts not found or timed out).")
        return

    print(f"\r  {' ' * 50}\r", end="")
    print(f"  {C.BCYAN}🔊 Playing {label}...{C.RESET}")

    try:
        if platform.system() == "Darwin":
            subprocess.run(["afplay", tmp_file], timeout=15)
        elif is_command_available("aplay"):
            # Convert to wav first for aplay
            subprocess.run(["aplay", tmp_file], timeout=15)
        elif is_command_available("mpv"):
            subprocess.run(["mpv", "--no-video", tmp_file], timeout=15, capture_output=True)
        elif is_command_available("ffplay"):
            subprocess.run(["ffplay", "-nodisp", "-autoexit", tmp_file],
                           timeout=15, capture_output=True)
        else:
            warn("No audio player found — skipping playback.")
    except subprocess.TimeoutExpired:
        pass
    except Exception:
        warn("Playback failed — but the voice is saved.")
    finally:
        try:
            os.unlink(tmp_file)
        except OSError:
            pass

    print()
    if not prompt_yn("Happy with this voice?"):
        print()
        return step_voice()  # Let them pick again


def step_email():
    step_header(4, 8, "Email Integration", "📧")
    print(f"  {C.DIM}HERMES can read, search, and draft emails for you.{C.RESET}")
    print(f"  {C.DIM}This uses himalaya — a fast terminal email client.{C.RESET}")
    print()

    if not prompt_yn("Enable email integration?", default=True):
        info("Email integration skipped. You can enable it later.")
        return {"enabled": False, "address": "", "provider": ""}

    email = prompt("Your email address")
    if not email or "@" not in email:
        warn("That doesn't look like a valid email. Skipping email setup.")
        return {"enabled": False, "address": "", "provider": ""}

    # Detect provider
    domain = email.split("@")[1].lower()
    if "gmail" in domain or "google" in domain:
        provider = "gmail"
    elif "outlook" in domain or "hotmail" in domain or "live" in domain:
        provider = "outlook"
    elif "icloud" in domain or "me.com" in domain or "mac.com" in domain:
        provider = "icloud"
    else:
        provider = "imap"

    print()
    # Check himalaya
    installed = offer_brew_install("himalaya")
    if not installed:
        warn("Email will be enabled in config but won't work until himalaya is installed.")

    return {"enabled": True, "address": email, "provider": provider}


def step_calendar():
    step_header(5, 8, "Calendar Integration", "📅")
    print(f"  {C.DIM}HERMES can check your calendar and manage events.{C.RESET}")
    print()

    if not prompt_yn("Enable calendar integration?", default=True):
        info("Calendar skipped.")
        return {"enabled": False}

    # On macOS we can use native calendar access or icalBuddy
    if platform.system() == "Darwin":
        if is_command_available("icalBuddy"):
            success("icalBuddy found — calendar access is ready.")
        else:
            info("On macOS, HERMES can use native calendar access.")
            offer_brew_install("icalBuddy", "ical-buddy")

    return {"enabled": True}


def step_reminders():
    step_header(6, 8, "Reminders Integration", "⏰")
    print(f"  {C.DIM}HERMES can set and manage reminders for you.{C.RESET}")
    print()

    if not prompt_yn("Enable reminders?", default=True):
        info("Reminders skipped.")
        return {"enabled": False}

    if platform.system() == "Darwin":
        info("On macOS, HERMES uses native Reminders via AppleScript.")
        success("Reminders integration is ready.")

    return {"enabled": True}


def step_preset(email_cfg, cal_cfg, rem_cfg):
    step_header(7, 8, "Choose Your Setup", "🎯")
    print(f"  {C.DIM}Pick a preset to get started quickly, or customise everything.{C.RESET}")
    print()

    presets = [
        ("minimal",  f"🟢 {C.BOLD}Minimal{C.RESET}     — Chat + voice only, no extra tools"),
        ("personal", f"🔵 {C.BOLD}Personal{C.RESET}    — Chat + email + calendar + reminders"),
        ("adobe-ea", f"🟣 {C.BOLD}Adobe EA{C.RESET}    — Everything + dashboard + briefing + NotePlan"),
        ("custom",   f"⚙️  {C.BOLD}Custom{C.RESET}      — Pick and choose what you want"),
    ]

    preset = prompt_choice("Which preset fits you best?", presets, default="personal")

    modules = {
        "email":      email_cfg,
        "calendar":   cal_cfg,
        "reminders":  rem_cfg,
        "dashboard":  {"enabled": False},
        "briefing":   {"enabled": False},
        "noteplan":   {"enabled": False, "path": ""},
        "web_search": {"enabled": True},
        "terminal":   {"enabled": True},
    }

    if preset == "minimal":
        modules["email"]["enabled"] = False
        modules["calendar"]["enabled"] = False
        modules["reminders"]["enabled"] = False
        modules["web_search"]["enabled"] = False
        modules["terminal"]["enabled"] = False

    elif preset == "personal":
        # Keep email/calendar/reminders as configured
        pass

    elif preset == "adobe-ea":
        modules["email"]["enabled"] = email_cfg.get("enabled", True)
        modules["calendar"]["enabled"] = True
        modules["reminders"]["enabled"] = True
        modules["dashboard"]["enabled"] = True
        modules["briefing"]["enabled"] = True
        modules["noteplan"]["enabled"] = True

    elif preset == "custom":
        print()
        print(f"  {C.BOLD}Toggle each feature on or off:{C.RESET}")
        print()
        modules["web_search"]["enabled"] = prompt_yn("  🌐 Web search?", default=True)
        modules["terminal"]["enabled"]   = prompt_yn("  💻 Terminal commands?", default=True)
        modules["dashboard"]["enabled"]  = prompt_yn("  📊 Client dashboard?", default=False)
        modules["briefing"]["enabled"]   = prompt_yn("  📋 Daily briefing?", default=False)
        modules["noteplan"]["enabled"]   = prompt_yn("  📝 NotePlan integration?", default=False)

    print()
    preset_labels = {"minimal": "Minimal", "personal": "Personal",
                     "adobe-ea": "Adobe EA", "custom": "Custom"}
    success(f"Preset: {C.BOLD}{preset_labels[preset]}{C.RESET}")

    return preset, modules


def step_noteplan(modules):
    if not modules.get("noteplan", {}).get("enabled"):
        return modules

    step_header(8, 8, "NotePlan Setup", "📝")
    default_path = "~/Library/Containers/co.noteplan.NotePlan-setapp/Data/Library/Application Support/co.noteplan.NotePlan-setapp/Notes/"
    print(f"  {C.DIM}HERMES can search and reference your NotePlan notes.{C.RESET}")
    print()
    print(f"  {C.DIM}Default path:{C.RESET}")
    print(f"  {C.DIM}{default_path}{C.RESET}")
    print()

    np_path = prompt("NotePlan notes path", default=default_path)
    expanded = os.path.expanduser(np_path)

    if os.path.isdir(expanded):
        success(f"NotePlan notes directory found!")
    else:
        warn(f"Directory not found: {expanded}")
        info("You can update the path in config.json later.")

    modules["noteplan"]["path"] = np_path
    return modules


def generate_system_prompt(user_name, address_style, preset, modules):
    """Generate a customised system prompt based on user preferences."""

    # Address handling
    if address_style == "first_name":
        first = user_name.split()[0]
        address_line = f'Address the user as "{first}".'
    elif address_style == "formal":
        last = user_name.split()[-1]
        address_line = f'Address the user formally as "Mr/Ms {last}".'
    else:
        address_line = "Do not use the user's name unless they ask you to."

    # Build capabilities list
    capabilities = []
    if modules.get("email", {}).get("enabled"):
        capabilities.append("- Email: Read, search, and draft emails via himalaya")
    if modules.get("calendar", {}).get("enabled"):
        capabilities.append("- Calendar: Check schedule, create and manage events")
    if modules.get("reminders", {}).get("enabled"):
        capabilities.append("- Reminders: Set, list, and manage reminders")
    if modules.get("web_search", {}).get("enabled"):
        capabilities.append("- Web Search: Search the internet for current information")
    if modules.get("terminal", {}).get("enabled"):
        capabilities.append("- Terminal: Execute shell commands when needed")
    if modules.get("dashboard", {}).get("enabled"):
        capabilities.append("- Dashboard: Access client dashboard and project status")
    if modules.get("briefing", {}).get("enabled"):
        capabilities.append("- Daily Briefing: Compile morning briefings from calendar, email, and tasks")
    if modules.get("noteplan", {}).get("enabled"):
        capabilities.append("- NotePlan: Search and reference notes from NotePlan")

    cap_block = "\n".join(capabilities) if capabilities else "- Chat and voice conversation only"

    prompt = f"""You are HERMES, an intelligent British voice assistant. You speak with a refined but warm British English style — articulate, helpful, and occasionally witty.

{address_line}

Your personality:
- Professional yet personable — like a skilled executive assistant
- Clear and concise in speech (remember, responses are spoken aloud)
- Proactive — anticipate what the user might need next
- Honest about limitations — never fabricate information

Your capabilities:
{cap_block}

Guidelines:
- Keep responses conversational and suitable for text-to-speech
- Avoid markdown formatting, bullet points, or code blocks in spoken responses
- Use natural sentence structure
- When performing actions, briefly confirm what you're doing
- If something fails, explain simply and suggest alternatives
- For complex information, offer to break it into parts"""

    if preset == "adobe-ea":
        prompt += """

Adobe EA Context:
- You serve as an executive assistant in a professional environment
- Be aware of client relationships and project timelines
- Prioritise urgent communications and deadlines
- Offer to compile daily briefings proactively"""

    return prompt


def save_config(config):
    """Save configuration to config.json and .env."""
    config_path = os.path.join(PROJECT_ROOT, "config.json")
    env_path = os.path.join(PROJECT_ROOT, ".env")

    # Save config.json
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    # Save .env
    with open(env_path, "w") as f:
        f.write(f"OPENROUTER_API_KEY={config['openrouter_api_key']}\n")

    # Set restrictive permissions on .env
    try:
        os.chmod(env_path, 0o600)
    except OSError:
        pass

    return config_path, env_path


def show_summary(config):
    """Display a summary of the configuration."""
    clear()
    banner()

    print(f"  {C.BGREEN}{C.BOLD}✨ Setup Complete!{C.RESET}")
    print()
    print(f"  {C.GRAY}{'─' * 50}{C.RESET}")
    print()
    print(f"  {C.BOLD}👤 Name:{C.RESET}       {config['user_name']}")
    print(f"  {C.BOLD}🗣️ Voice:{C.RESET}      {config['voice']}")
    print(f"  {C.BOLD}🔑 API Key:{C.RESET}    {config['openrouter_api_key'][:8]}...{config['openrouter_api_key'][-4:]}")
    print(f"  {C.BOLD}🎯 Preset:{C.RESET}     {config['preset']}")
    print()

    # Module status
    print(f"  {C.BOLD}Modules:{C.RESET}")
    module_icons = {
        "email": "📧", "calendar": "📅", "reminders": "⏰",
        "web_search": "🌐", "terminal": "💻", "dashboard": "📊",
        "briefing": "📋", "noteplan": "📝",
    }
    for name, cfg in config["modules"].items():
        icon = module_icons.get(name, "•")
        enabled = cfg.get("enabled", False)
        status = f"{C.BGREEN}ON{C.RESET}" if enabled else f"{C.DIM}off{C.RESET}"
        extra = ""
        if name == "email" and enabled and cfg.get("address"):
            extra = f" {C.DIM}({cfg['address']}){C.RESET}"
        print(f"    {icon} {name:<12} {status}{extra}")

    print()
    print(f"  {C.GRAY}{'─' * 50}{C.RESET}")
    print()
    print(f"  {C.DIM}Config saved to:{C.RESET}  config.json")
    print(f"  {C.DIM}API key saved to:{C.RESET} .env")
    print()
    print(f"  {C.BOLD}To start HERMES, run:{C.RESET}")
    print(f"    {C.BCYAN}python main.py{C.RESET}")
    print()
    print(f"  {C.DIM}To re-run this wizard:{C.RESET}")
    print(f"    {C.DIM}python setup_wizard.py{C.RESET}")
    print()


# ── Main Wizard Flow ─────────────────────────────────────────────────────────

def main():
    try:
        # Welcome
        step_welcome()

        # Step 1: Name
        clear()
        banner()
        user_name, address_style = step_name()
        time.sleep(0.5)

        # Step 2: API Key
        clear()
        banner()
        api_key = step_api_key()
        time.sleep(0.5)

        # Step 3: Voice
        clear()
        banner()
        voice = step_voice()
        time.sleep(0.5)

        # Step 4: Email
        clear()
        banner()
        email_cfg = step_email()
        time.sleep(0.5)

        # Step 5: Calendar
        clear()
        banner()
        cal_cfg = step_calendar()
        time.sleep(0.5)

        # Step 6: Reminders
        clear()
        banner()
        rem_cfg = step_reminders()
        time.sleep(0.5)

        # Step 7: Preset
        clear()
        banner()
        preset, modules = step_preset(email_cfg, cal_cfg, rem_cfg)
        time.sleep(0.5)

        # Step 8: NotePlan (conditional)
        if modules.get("noteplan", {}).get("enabled"):
            clear()
            banner()
            modules = step_noteplan(modules)
            time.sleep(0.5)

        # Generate system prompt
        system_prompt = generate_system_prompt(user_name, address_style, preset, modules)

        # Build config
        config = {
            "user_name": user_name,
            "address_style": address_style,
            "voice": voice,
            "openrouter_api_key": api_key,
            "preset": preset,
            "modules": modules,
            "system_prompt": system_prompt,
        }

        # Save
        save_config(config)

        # Summary
        show_summary(config)

    except KeyboardInterrupt:
        print()
        print()
        print(f"  {C.BYELLOW}Setup cancelled.{C.RESET} No changes were saved.")
        print(f"  {C.DIM}Run python setup_wizard.py to try again.{C.RESET}")
        print()
        sys.exit(1)
    except EOFError:
        print()
        print(f"  {C.BYELLOW}Input ended unexpectedly.{C.RESET}")
        sys.exit(1)


if __name__ == "__main__":
    main()

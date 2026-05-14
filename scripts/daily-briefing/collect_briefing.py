#!/usr/bin/env python3
"""
Daily Briefing Data Collector
Gathers calendar, meeting notes, and prep requirements for Adobe Enterprise Architect.
Outputs structured JSON to ~/.hermes/daily-briefing/briefing_data.json
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

# === Configuration ===
HERMES_BASE = Path.home() / ".hermes"
OUTPUT_DIR = HERMES_BASE / "daily-briefing"
OUTPUT_FILE = OUTPUT_DIR / "briefing_data.json"
CLIENT_REGISTRY = HERMES_BASE / "scripts" / "meeting-processor" / "client_registry.json"
NOTEPLAN_BASE = (Path.home() / "Library" / "Containers" / "co.noteplan.NotePlan-setapp" /
                 "Data" / "Library" / "Application Support" / "co.noteplan.NotePlan-setapp")
MEETINGS_BASE = NOTEPLAN_BASE / "Notes" / "Meetings"
MARKDOWN_IMPORT = NOTEPLAN_BASE / "Notes" / "Markdown Import"
ACAL_BIN = "/opt/homebrew/bin/acal"

# Event classification keywords
SPEAKING_KEYWORDS = [
    "architecture", "technical", "spec", "design review", "pov",
    "workshop", "demo", "presentation", "briefing"
]
DISCOVERY_KEYWORDS = ["discovery", "intro", "kickoff", "first call"]

# Slack channels to monitor
SLACK_CHANNELS = [
    "#aep-updates", "#ajo-updates", "#aem-updates", "#genai-updates",
    "#workfront-updates", "#target-updates", "#analytics-updates"
]

# === Calendar Fetch ===
def fetch_calendar(date_str):
    """Fetch calendar events for a single day via acal. Single-day only to avoid crash."""
    next_day = (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    cmd = f'{ACAL_BIN} events list --from {date_str} --to {next_day} --format json'
    tmp_file = f'/tmp/briefing_cal_{date_str}.json'
    os.system(f'{cmd} > {tmp_file} 2>/dev/null')
    try:
        with open(tmp_file, 'r') as f:
            raw = f.read()
        # Strip control characters that acal sometimes emits
        cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', raw)
        data = json.loads(cleaned)
        return data.get("data", [])
    except Exception as e:
        print(f"Warning: Could not parse calendar for {date_str}: {e}", file=sys.stderr)
        return []


# === Client Registry ===
def load_client_registry():
    """Load client names from the meeting-processor client registry."""
    try:
        with open(CLIENT_REGISTRY, 'r') as f:
            registry = json.load(f)
        # Registry may be dict with client names as keys, or a list
        if isinstance(registry, dict):
            return list(registry.keys())
        elif isinstance(registry, list):
            names = []
            for item in registry:
                if isinstance(item, dict):
                    name = item.get("name") or item.get("client_name") or item.get("client") or ""
                    if name:
                        names.append(name)
                elif isinstance(item, str):
                    names.append(item)
            return names
        return []
    except Exception as e:
        print(f"Warning: Could not load client registry: {e}", file=sys.stderr)
        return []


def load_client_registry_raw():
    """Load raw client registry data for TPS section."""
    try:
        with open(CLIENT_REGISTRY, 'r') as f:
            return json.load(f)
    except Exception:
        return {}


# === Event Classification ===
def classify_event(title, client_names):
    """Classify a calendar event by type."""
    title_lower = title.lower()

    # Filter out NotePlan mirror events
    if title.startswith(": "):
        return None  # skip

    # Check speaking/presenting
    for kw in SPEAKING_KEYWORDS:
        if kw in title_lower:
            return {
                "type": "SPEAKING",
                "badge": "🎤 SPEAKING",
                "action_label": "Prep Deck",
                "action_url": f"hermes://prompt/Help me prepare a presentation for: {title}",
                "flag": "Prep deck needed"
            }

    # Check discovery
    for kw in DISCOVERY_KEYWORDS:
        if kw in title_lower:
            company = extract_company_name(title)
            return {
                "type": "DISCOVERY",
                "badge": "🔍 DISCOVERY",
                "action_label": "Research",
                "action_url": f"hermes://prompt/Help me research for discovery call: {title}",
                "flag": "Research needed",
                "company": company
            }

    # Check client meeting
    for client in client_names:
        if client.lower() in title_lower:
            return {
                "type": "CLIENT",
                "badge": "👥 CLIENT",
                "action_label": "Review Notes",
                "action_url": f"hermes://prompt/Show me recent meeting notes for: {client}",
                "flag": "Review notes",
                "client": client
            }

    # Internal/other
    return {
        "type": "INTERNAL",
        "badge": "📅 INTERNAL",
        "action_label": None,
        "action_url": None,
        "flag": None
    }


def extract_company_name(title):
    """Try to extract a company name from an event title."""
    # Remove common prefixes
    cleaned = re.sub(r'(?i)(discovery|intro|kickoff|first call|call|meeting|with)\s*[-:—]?\s*', '', title)
    # Remove time patterns
    cleaned = re.sub(r'\d{1,2}:\d{2}', '', cleaned)
    # Take first meaningful chunk
    cleaned = cleaned.strip().strip('-:—').strip()
    if cleaned:
        # Take first 3 words max as company name
        words = cleaned.split()[:3]
        return ' '.join(words)
    return title


# === NotePlan Meeting Notes ===
def scan_meeting_notes(target_date):
    """Scan NotePlan for meeting notes from a specific date."""
    notes = []
    year = target_date.strftime("%Y")
    month_num = target_date.strftime("%m")
    month_name = target_date.strftime("%b")
    date_str = target_date.strftime("%Y-%m-%d")
    date_str_alt = target_date.strftime("%Y%m%d")

    # Check Meetings folder
    meetings_dir = MEETINGS_BASE / year / f"{month_num} - {month_name}"
    if meetings_dir.exists():
        try:
            for f in meetings_dir.iterdir():
                if f.is_file() and date_str in f.name:
                    note = parse_meeting_note(f)
                    if note:
                        notes.append(note)
        except Exception as e:
            print(f"Warning: Could not scan meetings dir: {e}", file=sys.stderr)

    # Check Markdown Import folder
    if MARKDOWN_IMPORT.exists():
        try:
            for f in MARKDOWN_IMPORT.iterdir():
                if f.is_file() and (date_str in f.name or date_str_alt in f.name):
                    note = parse_meeting_note(f)
                    if note:
                        notes.append(note)
        except Exception as e:
            print(f"Warning: Could not scan markdown import: {e}", file=sys.stderr)

    return notes


def parse_meeting_note(filepath):
    """Parse a meeting note file for title and action items."""
    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
    except Exception as e:
        print(f"Warning: Could not read {filepath}: {e}", file=sys.stderr)
        return None

    # Extract title (first heading or filename)
    title = filepath.stem
    for line in content.split('\n'):
        line = line.strip()
        if line.startswith('# '):
            title = line[2:].strip()
            break
        elif line.startswith('## '):
            title = line[3:].strip()
            break

    # Count action items
    action_count = 0
    for line in content.split('\n'):
        if '- [ ]' in line or 'Action Item' in line or 'TODO' in line:
            action_count += 1

    return {
        "title": title,
        "file_path": str(filepath),
        "file_name": filepath.name,
        "action_items": action_count,
        "action_url": f"hermes://prompt/Review meeting notes and extract action items from: {filepath}"
    }


# === Active Clients for TPS ===
def get_active_clients(registry_data):
    """Extract active/urgent client list from NotePlan client cards with real data."""
    import re
    NOTEPLAN_CLIENTS = NOTEPLAN_BASE / "Notes" / "Clients 2026"
    clients = []

    # Scan Urgent/ and Active/ folders for client cards
    for priority, folder_name in [("🔴 Urgent", "Urgent"), ("🟢 Active", "Active")]:
        folder = NOTEPLAN_CLIENTS / folder_name
        if not folder.exists():
            continue
        for card_file in sorted(folder.glob("*.txt")):
            try:
                with open(card_file, 'r') as f:
                    content = f.read()
            except Exception:
                continue

            name = card_file.stem
            # Clean up name
            if name.startswith("Untitled"):
                continue

            # Parse key fields from card
            dr_num = ""
            revenue = ""
            close_date = ""
            phase = ""
            status_label = folder_name

            for line in content.split('\n'):
                line_stripped = line.strip()
                if line_stripped.startswith("### DR") or "DR:" in line_stripped:
                    dr_match = re.search(r'DR\d{7}', line_stripped) or re.search(r'DR#?\s*(\d+)', content)
                    if dr_match:
                        raw = dr_match.group(0)
                        # Normalize: always DR followed by digits, no # or spaces
                        digits = re.search(r'\d{6,}', raw)
                        dr_num = f"DR{digits.group(0)}" if digits else raw.replace('#', '').replace(' ', '')
                if "Estimated Revenue" in line_stripped or "Revenue" in line_stripped:
                    rev_match = re.search(r'USD\s*([\d,]+)', content[content.index(line_stripped):content.index(line_stripped)+200])
                    if rev_match:
                        revenue = f"${rev_match.group(1)}"
                if "Close Date" in line_stripped:
                    # Next non-empty line usually has the date
                    idx = content.index(line_stripped) + len(line_stripped)
                    rest = content[idx:idx+100].strip()
                    date_match = re.search(r'(\d{1,2}/\d{1,2}/\d{4})', rest)
                    if date_match:
                        close_date = date_match.group(1)
                if line_stripped.startswith("phase:"):
                    phase = line_stripped.split(":", 1)[1].strip()
                if line_stripped.startswith("active:"):
                    status_label = line_stripped.split(":", 1)[1].strip()

            # Build display name
            display_name = name.replace("HomeDepot", "Home Depot").replace("Nordstorms", "Nordstrom")

            detail_parts = []
            if dr_num:
                detail_parts.append(dr_num)
            if revenue:
                detail_parts.append(revenue)
            if close_date:
                detail_parts.append(f"Close: {close_date}")
            if phase:
                detail_parts.append(phase)
            detail = " | ".join(detail_parts) if detail_parts else status_label

            clients.append({
                "name": display_name,
                "priority": priority,
                "detail": detail,
                "dr": dr_num,
                "revenue": revenue,
                "close_date": close_date,
                "folder": folder_name,
                "summary": f"[Click Generate to create TPS summary]"
            })

    return clients


# === Main Collection ===
def main():
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    yesterday = (now - timedelta(days=1))
    is_friday = now.weekday() == 4  # Monday=0, Friday=4
    is_tps_day = now.weekday() in (3, 4)  # Thursday=3, Friday=4

    print(f"[Briefing Collector] Date: {today}, Friday: {is_friday}, TPS day: {is_tps_day}")

    # Load client registry
    client_names = load_client_registry()
    registry_raw = load_client_registry_raw()
    print(f"[Briefing Collector] Loaded {len(client_names)} clients from registry")

    # Fetch calendar
    print("[Briefing Collector] Fetching calendar...")
    raw_events = fetch_calendar(today)
    print(f"[Briefing Collector] Found {len(raw_events)} raw calendar events")

    # Classify events
    events = []
    discovery_events = []
    speaking_count = 0
    discovery_count = 0
    client_count = 0
    attention_count = 0

    for ev in raw_events:
        title = ev.get("title", "") or ev.get("summary", "") or ""
        if not title or title.startswith(": "):
            continue

        start = ev.get("startDate", "") or ev.get("start", {})
        if isinstance(start, dict):
            start = start.get("dateTime", "") or start.get("date", "")

        classification = classify_event(title, client_names)
        if classification is None:
            continue

        event_data = {
            "title": title,
            "start": start,
            "location": ev.get("location", ""),
            **classification
        }
        events.append(event_data)

        if classification["type"] == "SPEAKING":
            speaking_count += 1
            attention_count += 1
        elif classification["type"] == "DISCOVERY":
            discovery_count += 1
            attention_count += 1
            company = classification.get("company", title)
            discovery_events.append({
                "company": company,
                "event_title": title,
                "start": start,
                "status": "Not started",
                "links": {
                    "panorama": "https://panorama.corp.adobe.com/",
                    "salesforce": "https://adobe.lightning.force.com/",
                    "linkedin": f"https://www.linkedin.com/search/results/all/?keywords={quote(company)}"
                },
                "action_url": f"hermes://prompt/Run discovery research for {company}: check Panorama contracts, Salesforce opportunities, tech stack, industry insights, and LinkedIn profiles for attendees"
            })
        elif classification["type"] == "CLIENT":
            client_count += 1

    print(f"[Briefing Collector] Classified: {speaking_count} speaking, {discovery_count} discovery, {client_count} client")

    # Scan yesterday's meeting notes
    print("[Briefing Collector] Scanning yesterday's meeting notes...")
    meeting_notes = scan_meeting_notes(yesterday)
    notes_with_actions = sum(1 for n in meeting_notes if n["action_items"] > 0)
    if notes_with_actions > 0:
        attention_count += notes_with_actions
    print(f"[Briefing Collector] Found {len(meeting_notes)} meeting notes, {notes_with_actions} with action items")

    # TPS data (Thu-Fri)
    tps_clients = []
    if is_tps_day:
        tps_clients = get_active_clients(registry_raw)
        if tps_clients:
            attention_count += 1
        print(f"[Briefing Collector] TPS: {len(tps_clients)} active clients")

    # Slack channels
    slack_channels = []
    for ch in SLACK_CHANNELS:
        slack_channels.append({
            "name": ch,
            "last_checked": "Never",
            "action_url": f"hermes://prompt/Check Slack channel {ch} for recent product updates and summarize"
        })

    # Build output
    briefing_data = {
        "generated_at": now.isoformat(),
        "date": today,
        "date_display": now.strftime("%A, %B %d, %Y"),
        "is_friday": is_friday,
        "is_tps_day": is_tps_day,
        "summary": {
            "attention_count": attention_count,
            "speaking_count": speaking_count,
            "discovery_count": discovery_count,
            "client_count": client_count,
            "notes_with_actions": notes_with_actions,
            "total_events": len(events),
            "total_notes": len(meeting_notes)
        },
        "sections": {
            "calendar": {
                "events": events,
                "status": "action_required" if speaking_count > 0 or discovery_count > 0 else ("attention" if client_count > 0 else "done")
            },
            "discovery": {
                "items": discovery_events,
                "status": "action_required" if discovery_count > 0 else "done"
            },
            "meeting_notes": {
                "notes": meeting_notes,
                "yesterday_date": yesterday.strftime("%Y-%m-%d"),
                "yesterday_display": yesterday.strftime("%A, %B %d"),
                "status": "attention" if notes_with_actions > 0 else ("done" if meeting_notes else "done")
            },
            "tps": {
                "clients": tps_clients,
                "visible": is_tps_day,
                "status": "action_required" if is_tps_day and tps_clients else "done"
            },
            "slack_channels": {
                "channels": slack_channels,
                "status": "attention"
            },
            "product_updates": {
                "resources": [
                    {"name": "Adobe Experience League", "url": "https://experienceleague.adobe.com/", "icon": "📋"},
                    {"name": "Adobe Developer Blog", "url": "https://blog.developer.adobe.com/", "icon": "📋"},
                    {"name": "Adobe Tech Blog", "url": "https://medium.com/adobetech", "icon": "📋"},
                    {"name": "Adobe Release Notes", "url": "https://experienceleague.adobe.com/en/docs/release-notes/experience-cloud/current", "icon": "📋"}
                ],
                "status": "attention"
            },
            "field_readiness": {
                "resources": [
                    {"name": "Field Readiness Portal", "url": "#", "icon": "📋"},
                    {"name": "Internal Enablement", "url": "#", "icon": "📋"}
                ],
                "status": "attention"
            },
            "ai_watch": {
                "sources": [
                    {"name": "OpenAI Blog", "url": "https://openai.com/blog", "icon": "🤖"},
                    {"name": "Anthropic Blog", "url": "https://www.anthropic.com/research", "icon": "🤖"},
                    {"name": "Google AI Blog", "url": "https://blog.google/technology/ai/", "icon": "🤖"},
                    {"name": "Adobe Sensei/Firefly", "url": "https://www.adobe.com/sensei.html", "icon": "🤖"},
                    {"name": "Hacker News", "url": "https://news.ycombinator.com/", "icon": "🤖"}
                ],
                "status": "attention"
            }
        }
    }

    # Write output
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(briefing_data, f, indent=2)

    print(f"[Briefing Collector] Output written to {OUTPUT_FILE}")
    print(f"[Briefing Collector] Summary: {attention_count} items need attention | {speaking_count} decks to prep | {discovery_count} discovery calls")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Daily Briefing HTML Generator
Reads briefing_data.json and produces a single-file HTML dashboard.
"""
import json
import html
import sys
from pathlib import Path
from datetime import datetime

HERMES_BASE = Path.home() / ".hermes"
DATA_FILE = HERMES_BASE / "daily-briefing" / "briefing_data.json"
OUTPUT_FILE = HERMES_BASE / "daily-briefing" / "index.html"


def load_data():
    try:
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading briefing data: {e}", file=sys.stderr)
        return None


def esc(text):
    return html.escape(str(text)) if text else ""


def status_icon(status):
    if status == "done":
        return "✅"
    elif status == "attention":
        return "⚠️"
    elif status == "action_required":
        return "❌"
    return "ℹ️"


def generate_html(data):
    s = data["sections"]
    summary = data["summary"]

    # Date folder for NotePlan: "Work/May 14/" instead of "Work/"
    dt = datetime.strptime(data["date"], "%Y-%m-%d")
    date_folder = dt.strftime("%B %d").replace(" 0", " ")  # "May 14" not "May 04"
    np_folder = f"Work/{date_folder}"  # e.g. "Work/May 14"

    # Summary bar text
    summary_parts = []
    if summary["attention_count"] > 0:
        summary_parts.append(f'{summary["attention_count"]} items need attention')
    if summary["speaking_count"] > 0:
        summary_parts.append(f'{summary["speaking_count"]} decks to prep')
    if summary["discovery_count"] > 0:
        summary_parts.append(f'{summary["discovery_count"]} discovery calls')
    if summary["notes_with_actions"] > 0:
        summary_parts.append(f'{summary["notes_with_actions"]} notes with action items')
    summary_text = " | ".join(summary_parts) if summary_parts else "All clear — no items need attention"

    # === Section 1: Calendar ===
    cal_rows = ""
    for i, ev in enumerate(s["calendar"]["events"]):
        start = esc(ev.get("start", ""))
        # Try to extract just the time
        if "T" in start:
            try:
                dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                start = dt.strftime("%I:%M %p")
            except:
                pass
        title = esc(ev["title"])
        badge_class = ev["type"].lower()
        badge = esc(ev["badge"])
        flag = esc(ev.get("flag", ""))
        action_label = ev.get("action_label", "")
        action_url = ev.get("action_url", "")

        action_btn = ""
        done_btn = ""
        if action_label and action_url:
            item_id = f"cal-{i}"
            action_btn = f'<a href="{esc(action_url)}" class="action-btn action-btn-sm" onclick="markViewed(\'{item_id}\')">{esc(action_label)}</a>'
            done_btn = f'<button class="done-btn" onclick="toggleDone(\'{item_id}\', this)">✓ Done</button>'

        flag_html = f'<span class="flag">{flag}</span>' if flag else ""

        cal_rows += f'''
        <div class="event-row" id="row-cal-{i}" data-section="calendar" data-actionable="{"1" if action_label else "0"}">
            <span class="event-time">{start}</span>
            <span class="event-badge badge-{badge_class}">{badge}</span>
            <span class="event-title">{title}</span>
            {flag_html}
            {action_btn}
            {done_btn}
        </div>'''

    if not s["calendar"]["events"]:
        cal_rows = '<div class="empty-state">No events scheduled for today</div>'

    # === Section 2: Discovery Queue ===
    disc_rows = ""
    for item in s["discovery"]["items"]:
        company = esc(item["company"])
        links_html = f'''
            <a href="{esc(item['links']['panorama'])}" target="_blank" class="resource-link">🔗 Panorama</a>
            <a href="{esc(item['links']['salesforce'])}" target="_blank" class="resource-link">🔗 Salesforce</a>
            <a href="{esc(item['links']['linkedin'])}" target="_blank" class="resource-link">🔗 LinkedIn</a>
        '''
        disc_rows += f'''
        <div class="discovery-item">
            <div class="discovery-header">
                <strong>{company}</strong>
                <span class="status-badge status-not-started">{esc(item["status"])}</span>
            </div>
            <div class="discovery-links">{links_html}</div>
            <a href="{esc(item['action_url'])}" class="action-btn">Run Full Research</a>
        </div>'''

    if not s["discovery"]["items"]:
        disc_rows = '<div class="empty-state">No discovery calls today</div>'

    # === Section 3: Meeting Notes ===
    notes_rows = ""
    for note in s["meeting_notes"]["notes"]:
        title = esc(note["title"])
        actions = note["action_items"]
        action_text = f'<span class="action-count">Action items: {actions}</span>' if actions > 0 else '<span class="action-count zero">No action items</span>'
        notes_rows += f'''
        <div class="note-row">
            <span class="note-title">{title}</span>
            {action_text}
            <a href="{esc(note['action_url'])}" class="action-btn action-btn-sm">Review & Extract Tasks</a>
        </div>'''

    if not s["meeting_notes"]["notes"]:
        notes_rows = f'<div class="empty-state">No meeting notes found for {esc(s["meeting_notes"]["yesterday_display"])}</div>'

    # === Section 4: TPS Report ===
    tps_html = ""
    if s["tps"]["visible"]:
        tps_rows = ""
        for i, client in enumerate(s["tps"]["clients"]):
            tid = f"tps-{i}"
            priority = esc(client.get("priority", ""))
            detail = esc(client.get("detail", ""))
            tps_rows += f'''
            <div class="tps-row" id="row-{tid}" data-section="tps" data-actionable="1">
                <span class="tps-priority">{priority}</span>
                <strong class="tps-client-name">{esc(client["name"])}</strong>
                <span class="tps-detail">{detail}</span>
                <button class="done-btn" onclick="toggleDone('{tid}', this)">✓ Done</button>
            </div>'''
        if not s["tps"]["clients"]:
            tps_rows = '<div class="empty-state">No active/urgent clients found in NotePlan Clients 2026</div>'

        client_names = ", ".join([c["name"] for c in s["tps"]["clients"]])
        tps_prompt = f"Generate TPS Tracker updates for these clients: {client_names}. For EACH client provide: (1) Touch Points — select activity type + comment about what I did this week, (2) Executive Summary — brief high-level for management reporting. Base it on this week's meeting notes and calendar activity. Format ready to copy-paste into TPS Tracker at https://6gc.short.gy/xsctracker. IMPORTANT: DR numbers must be formatted as DR1234567 (no hash, no space — NOT DR#1234567). Also save to NotePlan {np_folder}/ folder as 'TPS Tracker Update — {esc(data['date'])}.txt' using shell cat redirect."

        tps_html = f'''
        <div class="card full-width" id="section-tps">
            <div class="card-header" onclick="toggleSection('tps')">
                <span class="section-icon">📊</span>
                <h2>TPS Report — {len(s["tps"]["clients"])} Active Clients</h2>
                <span class="status-indicator">{status_icon(s["tps"]["status"])}</span>
                <span class="collapse-icon" id="collapse-tps">▼</span>
            </div>
            <div class="card-content" id="content-tps">
                <div class="section-note">It's Friday — TPS updates due! Tracker: <a href="https://6gc.short.gy/xsctracker" target="_blank" style="color:#6ba3d6">https://6gc.short.gy/xsctracker</a> → Team: Enterprise Architect</div>
                {tps_rows}
                <div class="card-actions">
                    <a href="hermes://prompt/{esc(tps_prompt)}" class="action-btn" id="checkall-tps" onclick="runCheckAll(this, 'tps'); return false;">Generate TPS Summaries &amp; Save to NotePlan</a>
                </div>
            </div>
        </div>'''

    # === Section 5: Slack Channels ===
    slack_rows = ""
    for i, ch in enumerate(s["slack_channels"]["channels"]):
        sid = f"slack-{i}"
        slack_rows += f'''
        <div class="slack-row" id="row-{sid}" data-section="slack" data-actionable="1">
            <span class="channel-name">{esc(ch["name"])}</span>
            <span class="last-checked">Last checked: {esc(ch["last_checked"])}</span>
            <a href="{esc(ch['action_url'])}" class="action-btn action-btn-sm" onclick="markViewed('{sid}')">Check Channel</a>
            <button class="done-btn" onclick="toggleDone('{sid}', this)">✓ Done</button>
        </div>'''

    # === Section 6: Product Updates ===
    product_rows = ""
    for i, res in enumerate(s["product_updates"]["resources"]):
        pid = f"prod-{i}"
        check_prompt = f"Check {res['name']} for the latest Adobe product updates. Summarize what is new in 1-2 lines per update, include direct links. Then save a note to NotePlan {np_folder}/ folder as a .txt file titled 'Product Updates — {data['date']}' (append if it already exists). Use shell cat redirect to write. Format: ## {res['name']}\\n- [update summary] — [link]\\n"
        product_rows += f'''
        <div class="resource-row" id="row-{pid}" data-section="products" data-actionable="1">
            <span>{esc(res["icon"])}</span>
            <a href="{esc(res['url'])}" target="_blank" class="resource-link">{esc(res["name"])}</a>
            <a href="hermes://prompt/{esc(check_prompt)}" class="action-btn action-btn-sm" onclick="markViewed('{pid}')" style="margin-left:auto">Check</a>
            <button class="done-btn" onclick="toggleDone('{pid}', this)">✓ Done</button>
        </div>'''

    # === Section 7: Field Readiness ===
    field_rows = ""
    for i, res in enumerate(s["field_readiness"]["resources"]):
        fid = f"field-{i}"
        check_prompt = f"Check {res['name']} for new field enablement and product communication updates for customers. Summarize what is new in 1-2 lines per update with links. Save to NotePlan {np_folder}/ folder as 'Field Readiness Updates — {data['date']}.txt' (append if exists). Use shell cat redirect to write."
        field_rows += f'''
        <div class="resource-row" id="row-{fid}" data-section="field" data-actionable="1">
            <span>{esc(res["icon"])}</span>
            <a href="{esc(res['url'])}" target="_blank" class="resource-link">{esc(res["name"])}</a>
            <a href="hermes://prompt/{esc(check_prompt)}" class="action-btn action-btn-sm" onclick="markViewed('{fid}')" style="margin-left:auto">Check</a>
            <button class="done-btn" onclick="toggleDone('{fid}', this)">✓ Done</button>
        </div>'''

    # === Section 8: AI Watch ===
    ai_rows = ""
    for i, src in enumerate(s["ai_watch"]["sources"]):
        aid = f"ai-{i}"
        check_prompt = f"Check {src['name']} for the latest AI and technology developments from the past 48 hours. Focus on what impacts Adobe products (AEP, AJO, AEM, GenStudio, Firefly) and how it affects our customer proposals. Summarize 1-2 lines per development with links. Save to NotePlan {np_folder}/ folder as 'AI Tech Watch — {data['date']}.txt' (append if exists). Use shell cat redirect to write."
        ai_rows += f'''
        <div class="resource-row" id="row-{aid}" data-section="ai" data-actionable="1">
            <span>{esc(src["icon"])}</span>
            <a href="{esc(src['url'])}" target="_blank" class="resource-link">{esc(src["name"])}</a>
            <a href="hermes://prompt/{esc(check_prompt)}" class="action-btn action-btn-sm" onclick="markViewed('{aid}')" style="margin-left:auto">Check</a>
            <button class="done-btn" onclick="toggleDone('{aid}', this)">✓ Done</button>
        </div>'''

    # === TPS refresh JS (conditional on Thu-Fri) ===
    if data.get("is_tps_day", data.get("is_friday")):
        tps_refresh_js = (
            "steps.push('', '6. Generate TPS Tracker updates for all active/urgent clients. "
            "For EACH: (1) Touch Points with activity type + comment, (2) Executive Summary "
            "for management. Base on this weeks meetings and calendar. Format for copy-paste "
            "into TPS Tracker. Save to NotePlan ' + npFolder + '/ folder as TPS Tracker Update ' + theDate "
            "+ '.txt using shell cat redirect.');"
        )
    else:
        tps_refresh_js = "// Not Friday - skip TPS"

    # === Full HTML ===
    html_content = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Daily Briefing — {esc(data["date_display"])}</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Adobe Clean', Roboto, sans-serif;
    background: #1a1a2e;
    color: #e0e0e0;
    min-height: 100vh;
}}
.top-bar {{
    background: linear-gradient(135deg, #0f0f23 0%, #1a1a2e 100%);
    border-bottom: 2px solid #EB1000;
    padding: 16px 24px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px;
}}
.top-bar h1 {{
    font-size: 1.4em;
    font-weight: 600;
    color: #ffffff;
}}
.top-bar h1 span {{ color: #EB1000; }}
.top-bar .timestamp {{
    font-size: 0.85em;
    color: #888;
}}
.summary-bar {{
    background: #16213e;
    padding: 12px 24px;
    font-size: 0.95em;
    color: #f0c040;
    border-bottom: 1px solid #2a2a4a;
    display: flex;
    align-items: center;
    gap: 8px;
}}
.summary-bar .icon {{ font-size: 1.1em; }}
.grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
    padding: 20px 24px;
    max-width: 1400px;
    margin: 0 auto;
}}
@media (max-width: 900px) {{
    .grid {{ grid-template-columns: 1fr; }}
}}
.card {{
    background: #16213e;
    border-radius: 10px;
    border: 1px solid #2a2a4a;
    overflow: hidden;
    transition: box-shadow 0.2s;
}}
.card:hover {{
    box-shadow: 0 4px 20px rgba(235, 16, 0, 0.1);
}}
.card-header {{
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 14px 18px;
    background: #1e2a4a;
    cursor: pointer;
    user-select: none;
}}
.card-header h2 {{
    font-size: 1em;
    font-weight: 600;
    flex: 1;
    color: #fff;
}}
.section-icon {{ font-size: 1.2em; }}
.status-indicator {{ font-size: 1em; }}
.collapse-icon {{
    font-size: 0.8em;
    color: #666;
    transition: transform 0.3s;
}}
.collapse-icon.collapsed {{ transform: rotate(-90deg); }}
.card-content {{
    padding: 16px 18px;
    overflow: hidden;
    transition: max-height 0.4s ease, padding 0.3s;
}}
.card-content.collapsed {{
    max-height: 280px !important;
    padding-top: 10px;
    padding-bottom: 10px;
    mask-image: linear-gradient(to bottom, black 70%, transparent 100%);
    -webkit-mask-image: linear-gradient(to bottom, black 70%, transparent 100%);
}}
.card-actions {{
    padding-top: 12px;
    border-top: 1px solid #2a2a4a;
    margin-top: 12px;
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
}}
.event-row, .note-row, .slack-row, .tps-row, .discovery-item {{
    padding: 12px 0;
    border-bottom: 1px solid #2a2a4a;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 10px;
    line-height: 1.5;
}}
.event-row:last-child, .note-row:last-child, .slack-row:last-child, .tps-row:last-child {{
    border-bottom: none;
}}
.discovery-item {{
    flex-direction: column;
    align-items: flex-start;
}}
.discovery-header {{
    display: flex;
    align-items: center;
    gap: 10px;
    width: 100%;
}}
.discovery-links {{
    display: flex;
    gap: 12px;
    flex-wrap: wrap;
    padding: 6px 0;
}}
.event-time {{
    font-size: 0.85em;
    color: #888;
    min-width: 75px;
    font-family: 'SF Mono', 'Fira Code', monospace;
}}
.event-badge, .status-badge {{
    font-size: 0.75em;
    padding: 2px 8px;
    border-radius: 12px;
    font-weight: 600;
    white-space: nowrap;
}}
.badge-speaking {{ background: #8b0000; color: #ffcccb; }}
.badge-discovery {{ background: #4a3800; color: #ffd700; }}
.badge-client {{ background: #003366; color: #87ceeb; }}
.badge-internal {{ background: #2a2a4a; color: #aaa; }}
.status-not-started {{ background: #4a3800; color: #ffd700; }}
.event-title, .note-title {{
    flex: 1;
    font-size: 0.95em;
    min-width: 150px;
    color: #e8e8e8;
}}
.flag {{
    font-size: 0.8em;
    color: #f0c040;
    font-style: italic;
}}
.action-count {{
    font-size: 0.8em;
    color: #EB1000;
    font-weight: 600;
}}
.action-count.zero {{ color: #4a6; }}
.channel-name {{
    font-weight: 600;
    min-width: 160px;
    font-family: 'SF Mono', 'Fira Code', monospace;
    font-size: 0.9em;
}}
.last-checked {{
    font-size: 0.8em;
    color: #666;
    flex: 1;
}}
.tps-summary {{
    font-size: 0.9em;
    color: #aaa;
    font-style: italic;
    flex: 1;
    line-height: 1.6;
}}
.tps-priority {{
    font-size: 0.85em;
    min-width: 28px;
}}
.tps-client-name {{
    font-size: 0.95em;
    color: #fff;
    min-width: 120px;
}}
.tps-detail {{
    font-size: 0.85em;
    color: #888;
    flex: 1;
    font-family: 'SF Mono', 'Fira Code', monospace;
}}
.resource-row {{
    padding: 10px 0;
    display: flex;
    align-items: center;
    gap: 10px;
    border-bottom: 1px solid rgba(42,42,74,0.5);
}}
.resource-row:last-child {{ border-bottom: none; }}
.resource-link {{
    color: #6ba3d6;
    text-decoration: none;
    font-size: 0.95em;
}}
.resource-link:hover {{ color: #87ceeb; text-decoration: underline; }}
.action-btn {{
    display: inline-block;
    padding: 6px 14px;
    background: #EB1000;
    color: #fff;
    text-decoration: none;
    border-radius: 6px;
    font-size: 0.8em;
    font-weight: 600;
    transition: background 0.2s, transform 0.1s;
    white-space: nowrap;
}}
.action-btn:hover {{
    background: #ff2a1a;
    transform: translateY(-1px);
}}
.action-btn-sm {{
    padding: 4px 10px;
    font-size: 0.75em;
}}
.done-btn {{
    display: inline-block;
    padding: 4px 10px;
    background: #2a4a2a;
    color: #6c6;
    border: 1px solid #3a5a3a;
    border-radius: 6px;
    font-size: 0.75em;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s;
    white-space: nowrap;
    margin-left: 4px;
}}
.done-btn:hover {{ background: #3a6a3a; color: #8f8; }}
.done-btn.checked {{ background: #1a3a1a; color: #4a4; opacity: 0.6; }}
.action-btn.running {{
    background: #333;
    color: #aaa;
    pointer-events: none;
    position: relative;
}}
.action-btn.running::after {{
    content: '';
    display: inline-block;
    width: 12px;
    height: 12px;
    border: 2px solid #666;
    border-top-color: #fff;
    border-radius: 50%;
    margin-left: 6px;
    vertical-align: middle;
    animation: spin 0.8s linear infinite;
}}
@keyframes spin {{ to {{ transform: rotate(360deg); }} }}
.action-btn.completed {{
    background: #2a4a2a;
    color: #6c6;
    pointer-events: none;
}}
.action-btn.completed::before {{
    content: '✅ ';
}}
.item-done {{
    opacity: 0.4;
    text-decoration: line-through;
    text-decoration-color: #555;
}}
.stale-warning {{
    background: #4a2800;
    color: #ffa040;
    padding: 8px 24px;
    font-size: 0.85em;
    display: flex;
    align-items: center;
    gap: 8px;
    border-bottom: 1px solid #5a3800;
}}
.progress-bar {{
    display: inline-block;
    width: 60px;
    height: 6px;
    background: #2a2a4a;
    border-radius: 3px;
    overflow: hidden;
    margin-left: 8px;
    vertical-align: middle;
}}
.progress-fill {{
    height: 100%;
    background: #4a4;
    border-radius: 3px;
    transition: width 0.3s;
}}
.section-progress {{
    font-size: 0.75em;
    color: #888;
    margin-left: auto;
    white-space: nowrap;
}}
.empty-state {{
    padding: 20px;
    text-align: center;
    color: #666;
    font-style: italic;
}}
.section-note {{
    padding: 8px 12px;
    background: #2a2a4a;
    border-radius: 6px;
    margin-bottom: 12px;
    font-size: 0.85em;
    color: #f0c040;
}}
.full-width {{ grid-column: 1 / -1; }}
</style>
</head>
<body>

<div class="top-bar">
    <h1>Daily <span>Briefing</span> — {esc(data["date_display"])}</h1>
    <div class="timestamp">Last refreshed: {esc(data["generated_at"][:19].replace("T", " "))}</div>
    <button id="topbar-refresh-btn" class="action-btn action-btn-sm" style="margin-left:12px" onclick="doRefreshNow(this)">🔄 Refresh Now</button>
</div>

<div class="summary-bar">
    <span class="icon">📊</span>
    {esc(summary_text)}
</div>
<div class="stale-warning" id="stale-banner" style="display:none">
    <span>⏰</span> <span id="stale-text">Dashboard data is stale — run refresh to update.</span>
    <button id="refresh-now-btn" class="action-btn action-btn-sm" style="margin-left:auto" onclick="doRefreshNow(this)">Refresh Now</button>
</div>

<div class="grid">

    <!-- Section 1: Calendar -->
    <div class="card full-width" id="section-calendar">
        <div class="card-header" onclick="toggleSection('calendar')">
            <span class="section-icon">📅</span>
            <h2>Today's Calendar & Prep Needed</h2>
            <span class="status-indicator">{status_icon(s["calendar"]["status"])}</span>
            <span class="collapse-icon" id="collapse-calendar">▼</span>
        </div>
        <div class="card-content" id="content-calendar">
            {cal_rows}
        </div>
    </div>

    <!-- Section 2: Discovery Queue -->
    <div class="card" id="section-discovery">
        <div class="card-header" onclick="toggleSection('discovery')">
            <span class="section-icon">🔍</span>
            <h2>Discovery Call Research Queue</h2>
            <span class="status-indicator">{status_icon(s["discovery"]["status"])}</span>
            <span class="collapse-icon" id="collapse-discovery">▼</span>
        </div>
        <div class="card-content" id="content-discovery">
            {disc_rows}
        </div>
    </div>

    <!-- Section 3: Meeting Notes -->
    <div class="card" id="section-notes">
        <div class="card-header" onclick="toggleSection('notes')">
            <span class="section-icon">📝</span>
            <h2>Yesterday's Meeting Notes</h2>
            <span class="status-indicator">{status_icon(s["meeting_notes"]["status"])}</span>
            <span class="collapse-icon" id="collapse-notes">▼</span>
        </div>
        <div class="card-content" id="content-notes">
            <div class="section-note">Notes from {esc(s["meeting_notes"]["yesterday_display"])}</div>
            {notes_rows}
        </div>
    </div>

    {tps_html}

    <!-- Section 5: Slack Channels -->
    <div class="card" id="section-slack">
        <div class="card-header" onclick="toggleSection('slack')">
            <span class="section-icon">💬</span>
            <h2>Slack Product Channel Updates</h2>
            <span class="status-indicator">{status_icon(s["slack_channels"]["status"])}</span>
            <span class="collapse-icon" id="collapse-slack">▼</span>
        </div>
        <div class="card-content" id="content-slack">
            {slack_rows}
            <div class="card-actions">
                <a href="hermes://prompt/Check all Adobe product Slack channels ({', '.join(ch['name'] for ch in s['slack_channels']['channels'])}) for updates from the past 24 hours. Summarize what is new in 1-2 lines per channel with links to relevant threads. Save to NotePlan {np_folder}/ folder as 'Slack Channel Updates — {esc(data['date'])}.txt' using shell cat redirect. Group by channel." class="action-btn" id="checkall-slack" onclick="runCheckAll(this, 'slack')">Check All Channels &amp; Save to NotePlan</a>
            </div>
        </div>
    </div>

    <!-- Section 6: Product Updates -->
    <div class="card" id="section-products">
        <div class="card-header" onclick="toggleSection('products')">
            <span class="section-icon">📦</span>
            <h2>Product Development Updates</h2>
            <span class="status-indicator">{status_icon(s["product_updates"]["status"])}</span>
            <span class="collapse-icon" id="collapse-products">▼</span>
        </div>
        <div class="card-content" id="content-products">
            {product_rows}
            <div class="card-actions">
                <a href="hermes://prompt/Check ALL Adobe product sources (Experience League release notes, developer blog, tech blog) for updates from the past week. For each update found: 1-2 line summary + direct link. Save everything to NotePlan {np_folder}/ folder as 'Product Updates — {esc(data['date'])}.txt' using shell cat redirect. Group by source." class="action-btn" id="checkall-products" onclick="runCheckAll(this, 'products')">Check All &amp; Save to NotePlan</a>
            </div>
        </div>
    </div>

    <!-- Section 7: Field Readiness -->
    <div class="card" id="section-field">
        <div class="card-header" onclick="toggleSection('field')">
            <span class="section-icon">🎯</span>
            <h2>Field Readiness</h2>
            <span class="status-indicator">{status_icon(s["field_readiness"]["status"])}</span>
            <span class="collapse-icon" id="collapse-field">▼</span>
        </div>
        <div class="card-content" id="content-field">
            {field_rows}
            <div class="card-actions">
                <a href="hermes://prompt/Check Adobe field readiness and enablement resources for new product communication updates. What new messaging, talk tracks, or competitive positioning should I know about? Summarize 1-2 lines per update with links. Save to NotePlan {np_folder}/ folder as 'Field Readiness Updates — {esc(data['date'])}.txt' using shell cat redirect." class="action-btn" id="checkall-field" onclick="runCheckAll(this, 'field')">Check All &amp; Save to NotePlan</a>
            </div>
        </div>
    </div>

    <!-- Section 8: AI Watch -->
    <div class="card" id="section-ai">
        <div class="card-header" onclick="toggleSection('ai')">
            <span class="section-icon">🤖</span>
            <h2>AI & Technology Watch</h2>
            <span class="status-indicator">{status_icon(s["ai_watch"]["status"])}</span>
            <span class="collapse-icon" id="collapse-ai">▼</span>
        </div>
        <div class="card-content" id="content-ai">
            {ai_rows}
            <div class="card-actions">
                <a href="hermes://prompt/Give me a briefing on the latest AI developments from the past 48 hours. Focus on: (1) what impacts Adobe products — AEP, AJO, AEM, GenStudio, Firefly, Target, (2) how it affects our customer proposals, (3) competitive moves from Salesforce, Google, Microsoft. Summarize 1-2 lines per development with direct links. Save to NotePlan {np_folder}/ folder as 'AI Tech Watch — {esc(data['date'])}.txt' using shell cat redirect." class="action-btn" id="checkall-ai" onclick="runCheckAll(this, 'ai')">Full AI Briefing &amp; Save to NotePlan</a>
            </div>
        </div>
    </div>

</div>

<script>
const STORAGE_KEY = 'briefing-done-{esc(data["date"])}';
const HERMES_API = 'http://127.0.0.1:8766/api/prompt';

// Send a prompt to Hermes via the voice server API or hermes:// scheme
// Returns a promise that resolves when the job finishes
function sendPrompt(prompt, onDone) {{
    // file:// pages can't fetch http:// — use hermes:// directly
    if (window.location.protocol === 'file:') {{
        window.location.href = 'hermes://prompt/' + encodeURIComponent(prompt);
        return;
    }}
    fetch(HERMES_API, {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{prompt: prompt}})
    }}).then(r => r.json()).then(d => {{
        console.log('[Briefing] Prompt sent, job:', d.job_id);
        if (d.job_id) pollJob(d.job_id, onDone);
    }}).catch(err => {{
        console.log('[Briefing] API failed, trying hermes:// scheme:', err.message);
        window.location.href = 'hermes://prompt/' + encodeURIComponent(prompt);
    }});
}}

// Poll job status until done
function pollJob(jobId, onDone) {{
    const poll = () => {{
        fetch(HERMES_API.replace('/prompt', '/prompt/' + jobId))
        .then(r => r.json())
        .then(d => {{
            if (d.status === 'running') {{
                setTimeout(poll, 3000);
            }} else {{
                console.log('[Briefing] Job done:', jobId, d);
                if (onDone) onDone(d);
            }}
        }}).catch(() => setTimeout(poll, 5000));
    }};
    setTimeout(poll, 3000);
}}

function getState() {{
    try {{ return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{{}}'); }}
    catch {{ return {{}}; }}
}}
function saveState(state) {{
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}}

// Toggle section collapse
function toggleSection(name) {{
    const content = document.getElementById('content-' + name);
    const icon = document.getElementById('collapse-' + name);
    if (content.classList.contains('collapsed')) {{
        // Expanding — animate to scrollHeight then remove max-height cap
        content.classList.remove('collapsed');
        content.style.maxHeight = content.scrollHeight + 'px';
        icon.classList.remove('collapsed');
        setTimeout(() => {{ content.style.maxHeight = 'none'; }}, 400);
    }} else {{
        // Collapsing — set explicit max-height first so transition works
        content.style.maxHeight = content.scrollHeight + 'px';
        requestAnimationFrame(() => {{
            content.classList.add('collapsed');
            icon.classList.add('collapsed');
        }});
    }}
}}

// Mark item as done (toggle)
function toggleDone(itemId, btn) {{
    const state = getState();
    const row = document.getElementById('row-' + itemId);
    if (state[itemId]) {{
        delete state[itemId];
        if (row) row.classList.remove('item-done');
        if (btn) {{ btn.textContent = '✓ Done'; btn.classList.remove('checked'); }}
    }} else {{
        state[itemId] = Date.now();
        if (row) row.classList.add('item-done');
        if (btn) {{ btn.textContent = '✓ Done'; btn.classList.add('checked'); }}
    }}
    saveState(state);
    updateAllSectionStatus();
}}

// Mark item as viewed (when action link clicked)
function markViewed(itemId) {{
    const state = getState();
    state[itemId + '-viewed'] = Date.now();
    saveState(state);
}}

// Handle "Check All" master buttons — spinner, then mark complete after delay
function runCheckAll(btn, sectionName) {{
    const origText = btn.textContent;
    btn.classList.add('running');
    btn.textContent = '⏳ Running...';

    // Extract and send the prompt from the href (hermes://prompt/...)
    const href = btn.getAttribute('href') || '';
    const markComplete = () => {{
        btn.classList.remove('running');
        btn.textContent = '✅ Done — Mark Complete';
        btn.style.background = '#2a4a2a';
        btn.style.color = '#6c6';
        btn.style.border = '1px solid #3a5a3a';
        btn.style.pointerEvents = 'auto';
        btn.style.cursor = 'pointer';
        btn.removeAttribute('href');
        btn.onclick = function(e) {{
            e.preventDefault();
            // Mark ALL items in this section as done
            document.querySelectorAll('[data-section="' + sectionName + '"][data-actionable="1"]').forEach(row => {{
                const rid = row.id.replace('row-', '');
                const doneBtn = row.querySelector('.done-btn');
                if (doneBtn && !doneBtn.classList.contains('checked')) {{
                    toggleDone(rid, doneBtn);
                }}
            }});
            btn.classList.add('completed');
            btn.textContent = 'Saved to NotePlan';
            btn.onclick = null;
        }};
    }};

    if (href.startsWith('hermes://prompt/')) {{
        const prompt = decodeURIComponent(href.replace('hermes://prompt/', ''));
        sendPrompt(prompt, markComplete);
    }} else {{
        // No prompt, just mark complete after 5s
        setTimeout(markComplete, 5000);
    }}

    // Track that this was triggered
    const state = getState();
    state['checkall-' + sectionName] = Date.now();
    saveState(state);
}}

// Update section header icons based on done state
function updateAllSectionStatus() {{
    const state = getState();
    const sections = {{}};

    // Gather actionable items per section
    document.querySelectorAll('[data-section][data-actionable="1"]').forEach(row => {{
        const sec = row.dataset.section;
        if (!sections[sec]) sections[sec] = {{ total: 0, done: 0 }};
        sections[sec].total++;
        const rid = row.id.replace('row-', '');
        if (state[rid]) sections[sec].done++;
    }});

    // Update header icons + progress
    for (const [sec, counts] of Object.entries(sections)) {{
        const indicator = document.querySelector('#section-' + sec + ' .status-indicator');
        const header = document.querySelector('#section-' + sec + ' .card-header');
        if (indicator) {{
            if (counts.total === 0) {{
                indicator.textContent = '✅';
            }} else if (counts.done >= counts.total) {{
                indicator.textContent = '✅';
            }} else if (counts.done > 0) {{
                indicator.textContent = '🔄';
            }}
            // else keep original icon
        }}
        // Add/update progress text
        let prog = header.querySelector('.section-progress');
        if (counts.total > 0) {{
            if (!prog) {{
                prog = document.createElement('span');
                prog.className = 'section-progress';
                header.insertBefore(prog, header.querySelector('.collapse-icon'));
            }}
            const pct = Math.round((counts.done / counts.total) * 100);
            prog.innerHTML = counts.done + '/' + counts.total +
                ' <span class="progress-bar"><span class="progress-fill" style="width:' + pct + '%"></span></span>';
        }}
    }}
}}

// Refresh Now — fires hermes:// prompt with spinner feedback
function doRefreshNow(btn) {{
    const origText = btn.textContent;
    btn.textContent = 'Refreshing...';
    btn.classList.add('running');
    btn.disabled = true;
    // Also disable the other refresh button if exists
    ['topbar-refresh-btn', 'refresh-now-btn'].forEach(id => {{
        const other = document.getElementById(id);
        if (other && other !== btn) {{
            other.textContent = 'Refreshing...';
            other.classList.add('running');
            other.disabled = true;
        }}
    }});
    // Fire comprehensive refresh prompt that runs ALL checks
    const theDate = '{esc(data["date"])}';
    const npFolder = 'Work/{date_folder}';
    const steps = [
        'Full daily briefing dashboard refresh. Do ALL of these steps:',
        '',
        '1. Run the data collector and HTML generator:',
        '   bash ~/.hermes/scripts/daily-briefing/refresh.sh',
        '',
        '2. Check ALL Adobe product sources (Experience League release notes, developer blog, tech blog) for updates from the past week. For each update: 1-2 line summary + direct link. Save to NotePlan ' + npFolder + '/ folder as "Product Updates — ' + theDate + '.txt" using shell cat redirect. Group by source.',
        '',
        '3. Check Adobe field readiness and enablement resources for new product communication updates. Summarize 1-2 lines per update with links. Save to NotePlan ' + npFolder + '/ folder as "Field Readiness Updates — ' + theDate + '.txt" using shell cat redirect.',
        '',
        '4. Full AI briefing: latest AI developments from past 48 hours. Focus on: (a) what impacts Adobe products — AEP, AJO, AEM, GenStudio, Firefly, Target, (b) how it affects customer proposals, (c) competitive moves from Salesforce, Google, Microsoft. Save to NotePlan ' + npFolder + '/ folder as "AI Tech Watch — ' + theDate + '.txt" using shell cat redirect.',
        '',
        '5. Check all Adobe product Slack channels for updates from the past 24 hours.'
    ];
    {tps_refresh_js}
    var nextStep = steps.length > 10 ? 7 : 6;
    steps.push('', nextStep + '. After all checks complete, regenerate the dashboard HTML: cd ~/.hermes/scripts/daily-briefing && python3 generate_briefing.py');
    steps.push('', (nextStep+1) + '. Open the refreshed dashboard: open ~/.hermes/daily-briefing/index.html');
    const prompt = steps.join('\\n');
    sendPrompt(prompt);
    // After 10s, show "check back" state (hermes runs async)
    setTimeout(() => {{
        [btn, ...document.querySelectorAll('#topbar-refresh-btn, #refresh-now-btn')].forEach(b => {{
            if (b) {{
                b.classList.remove('running');
                b.textContent = '⏳ Refresh sent — reload page when done';
                b.disabled = false;
                b.onclick = () => window.location.reload();
            }}
        }});
    }}, 10000);
}}

// Stale data check
function checkStale() {{
    const genTime = new Date('{esc(data["generated_at"])}');
    const now = new Date();
    const hoursOld = (now - genTime) / (1000 * 60 * 60);
    const banner = document.getElementById('stale-banner');
    const text = document.getElementById('stale-text');
    if (hoursOld > 2) {{
        const h = Math.floor(hoursOld);
        text.textContent = 'Dashboard data is ' + h + ' hours old — refresh for latest.';
        banner.style.display = 'flex';
    }}
}}

// Restore state on load
document.addEventListener('DOMContentLoaded', () => {{
    // Set initial max-heights — expanded sections get 'none' so content isn't clipped
    document.querySelectorAll('.card-content').forEach(el => {{
        if (el.classList.contains('collapsed')) {{
            el.style.maxHeight = '280px';
        }} else {{
            el.style.maxHeight = 'none';
        }}
    }});

    // Restore done states from localStorage
    const state = getState();
    for (const [itemId, timestamp] of Object.entries(state)) {{
        if (itemId.endsWith('-viewed')) continue;
        const row = document.getElementById('row-' + itemId);
        if (row) {{
            row.classList.add('item-done');
            const btn = row.querySelector('.done-btn');
            if (btn) btn.classList.add('checked');
        }}
    }}
    updateAllSectionStatus();
    checkStale();

    // Intercept all hermes://prompt/ links and route through sendPrompt API
    document.addEventListener('click', (e) => {{
        const link = e.target.closest('a[href^="hermes://prompt/"]');
        if (link) {{
            e.preventDefault();
            const href = link.getAttribute('href');
            const prompt = decodeURIComponent(href.replace('hermes://prompt/', ''));
            sendPrompt(prompt);
        }}
    }});

    // Restore "Check All" button states
    ['products', 'field', 'ai', 'tps', 'slack'].forEach(sec => {{
        if (state['checkall-' + sec]) {{
            const btn = document.getElementById('checkall-' + sec);
            if (btn) {{
                // Check if all items in section are done
                let allDone = true;
                document.querySelectorAll('[data-section="' + sec + '"][data-actionable="1"]').forEach(row => {{
                    const rid = row.id.replace('row-', '');
                    if (!state[rid]) allDone = false;
                }});
                if (allDone) {{
                    btn.classList.add('completed');
                    btn.textContent = 'Saved to NotePlan';
                    btn.onclick = null;
                }} else {{
                    btn.textContent = '✓ Mark Complete';
                    btn.style.background = '#2a4a2a';
                    btn.style.color = '#6c6';
                    btn.style.border = '1px solid #3a5a3a';
                    btn.removeAttribute('href');
                    btn.onclick = function(e) {{
                        e.preventDefault();
                        document.querySelectorAll('[data-section="' + sec + '"][data-actionable="1"]').forEach(row => {{
                            const rid = row.id.replace('row-', '');
                            const doneBtn = row.querySelector('.done-btn');
                            if (doneBtn && !doneBtn.classList.contains('checked')) {{
                                toggleDone(rid, doneBtn);
                            }}
                        }});
                        btn.classList.add('completed');
                        btn.textContent = 'Saved to NotePlan';
                        btn.onclick = null;
                    }};
                }}
            }}
        }}
    }});

    // Clean up old days' storage
    for (let i = 0; i < localStorage.length; i++) {{
        const key = localStorage.key(i);
        if (key && key.startsWith('briefing-done-') && key !== STORAGE_KEY) {{
            localStorage.removeItem(key);
        }}
    }}
}});
</script>

</body>
</html>'''

    return html_content


def main():
    data = load_data()
    if not data:
        print("No briefing data found. Run collect_briefing.py first.", file=sys.stderr)
        sys.exit(1)

    html_content = generate_html(data)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, 'w') as f:
        f.write(html_content)

    print(f"[Briefing Generator] Dashboard written to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()

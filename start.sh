#!/usr/bin/env bash
# ── HERMES Voice Assistant Launcher ──
cd "$(dirname "$0")"

# ── Colors ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

echo ""
echo -e "${MAGENTA}${BOLD}"
echo "    ╦ ╦ ╔═╗ ╦═╗ ╔╦╗ ╔═╗ ╔═╗"
echo "    ╠═╣ ║╣  ╠╦╝ ║║║ ║╣  ╚═╗"
echo "    ╩ ╩ ╚═╝ ╩╚═ ╩ ╩ ╚═╝ ╚═╝"
echo -e "${NC}"
echo -e "${DIM}    Voice Intelligence System${NC}"
echo ""

# ── Check venv exists ──
if [[ ! -d "venv" || ! -f "venv/bin/activate" ]]; then
    echo -e "${YELLOW}⚠${NC}  Hermes is not installed yet."
    echo -e "   Running installer first...\n"
    if [[ -f "install.sh" ]]; then
        bash install.sh
        exit $?
    else
        echo -e "${RED}✖  install.sh not found. Please reinstall Hermes.${NC}"
        exit 1
    fi
fi

# ── Activate virtual environment ──
source venv/bin/activate

# ── Source .env file ──
if [[ -f ".env" ]]; then
    set -a
    source .env
    set +a
fi

# ── Check if setup was completed ──
if [[ ! -f "config.json" ]]; then
    echo -e "${YELLOW}⚠${NC}  No configuration found."
    if [[ -f "setup_wizard.py" ]]; then
        echo -e "   Running setup wizard first...\n"
        python3 setup_wizard.py || {
            echo -e "${RED}✖  Setup wizard failed.${NC}"
            exit 1
        }
        echo ""
    else
        echo -e "${DIM}   (No setup_wizard.py found — continuing with defaults)${NC}"
    fi
fi

# ── Check for API key ──
if [[ -z "${OPENROUTER_API_KEY:-}" ]]; then
    echo -e "${YELLOW}⚠${NC}  No OPENROUTER_API_KEY found."
    echo -e "   Set it in .env or export it before running.\n"
    read -p "   Enter your OpenRouter API key (or press Enter to skip): " key
    if [[ -n "$key" ]]; then
        export OPENROUTER_API_KEY="$key"
        echo "OPENROUTER_API_KEY=$key" > .env
        echo -e "   ${GREEN}✔${NC} Key saved to .env\n"
    fi
fi

# ── Open browser after a delay ──
open_browser() {
    sleep 2
    local url="http://127.0.0.1:8766"
    if command -v open &>/dev/null; then
        open "$url"  # macOS
    elif command -v xdg-open &>/dev/null; then
        xdg-open "$url"  # Linux
    elif command -v wslview &>/dev/null; then
        wslview "$url"  # WSL
    elif command -v explorer.exe &>/dev/null; then
        explorer.exe "$url"  # WSL fallback
    fi
}

# ── Start server ──
echo -e "${GREEN}${BOLD}Starting Hermes...${NC}"
echo -e "${DIM}   Web UI: http://127.0.0.1:8766${NC}"
echo -e "${DIM}   Press Ctrl+C to stop${NC}"
echo ""

# Launch browser opener in background
open_browser &
BROWSER_PID=$!

# Run the server (foreground — Ctrl+C to stop)
python3 server.py

# Cleanup
kill $BROWSER_PID 2>/dev/null || true

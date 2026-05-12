#!/usr/bin/env bash
set -euo pipefail

# ── HERMES Voice Assistant — One-Click Installer ──
# Safe to run multiple times (idempotent)

cd "$(dirname "$0")"

# ── Colors ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m' # No Color

# ── Helper functions ──
info()    { echo -e "${CYAN}ℹ${NC}  $1"; }
success() { echo -e "${GREEN}✔${NC}  $1"; }
warn()    { echo -e "${YELLOW}⚠${NC}  $1"; }
fail()    { echo -e "${RED}✖  $1${NC}"; exit 1; }
step()    { echo -e "\n${BOLD}${BLUE}── $1 ──${NC}"; }

# ── Banner ──
echo ""
echo -e "${MAGENTA}${BOLD}"
echo "    ╦ ╦ ╔═╗ ╦═╗ ╔╦╗ ╔═╗ ╔═╗"
echo "    ╠═╣ ║╣  ╠╦╝ ║║║ ║╣  ╚═╗"
echo "    ╩ ╩ ╚═╝ ╩╚═ ╩ ╩ ╚═╝ ╚═╝"
echo -e "${NC}"
echo -e "${DIM}    Voice Intelligence System${NC}"
echo -e "${DIM}    ─────────────────────────${NC}"
echo ""

# ── Step 1: Detect OS ──
step "Detecting operating system"

OS="unknown"
if [[ "$OSTYPE" == "darwin"* ]]; then
    OS="macos"
    success "macOS detected ($(sw_vers -productVersion 2>/dev/null || echo 'unknown version'))"
elif [[ "$OSTYPE" == "linux"* ]]; then
    if grep -qi microsoft /proc/version 2>/dev/null; then
        OS="wsl"
        success "Windows WSL detected"
    else
        OS="linux"
        success "Linux detected"
    fi
else
    warn "Unknown OS: $OSTYPE — will try Linux-style installation"
    OS="linux"
fi

# ── Step 2: Find Python 3.11+ ──
step "Checking for Python 3.11+"

PYTHON_CMD=""
for candidate in python3.13 python3.12 python3.11 python3; do
    if command -v "$candidate" &>/dev/null; then
        # Check version is >= 3.11
        ver=$("$candidate" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
        major=$(echo "$ver" | cut -d. -f1)
        minor=$(echo "$ver" | cut -d. -f2)
        if [[ "$major" -ge 3 && "$minor" -ge 11 ]]; then
            PYTHON_CMD="$candidate"
            success "Found $candidate (Python $ver)"
            break
        fi
    fi
done

if [[ -z "$PYTHON_CMD" ]]; then
    echo ""
    fail "Python 3.11 or higher is required but not found.

    Install it:
      macOS:   brew install python@3.13
      Ubuntu:  sudo apt install python3.13 python3.13-venv
      Windows: https://python.org/downloads/

    Then re-run this installer."
fi

# ── Step 3: Package manager & system deps ──
step "Installing system dependencies"

if [[ "$OS" == "macos" ]]; then
    # Check for Homebrew
    if ! command -v brew &>/dev/null; then
        info "Homebrew not found — installing..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" || fail "Failed to install Homebrew"
        # Add brew to PATH for Apple Silicon
        if [[ -f /opt/homebrew/bin/brew ]]; then
            eval "$(/opt/homebrew/bin/brew shellenv)"
        fi
        success "Homebrew installed"
    else
        success "Homebrew already installed"
    fi

    # Install portaudio
    if brew list portaudio &>/dev/null; then
        success "portaudio already installed"
    else
        info "Installing portaudio (needed for microphone access)..."
        brew install portaudio || fail "Failed to install portaudio"
        success "portaudio installed"
    fi

    # Install ffmpeg (needed by whisper)
    if brew list ffmpeg &>/dev/null; then
        success "ffmpeg already installed"
    else
        info "Installing ffmpeg (needed for audio processing)..."
        brew install ffmpeg || fail "Failed to install ffmpeg"
        success "ffmpeg installed"
    fi

elif [[ "$OS" == "linux" || "$OS" == "wsl" ]]; then
    info "Installing system packages (may ask for sudo password)..."

    if command -v apt-get &>/dev/null; then
        sudo apt-get update -qq
        sudo apt-get install -y -qq portaudio19-dev python3-dev ffmpeg || fail "Failed to install system dependencies"
        success "System dependencies installed (apt)"
    elif command -v dnf &>/dev/null; then
        sudo dnf install -y portaudio-devel python3-devel ffmpeg || fail "Failed to install system dependencies"
        success "System dependencies installed (dnf)"
    elif command -v pacman &>/dev/null; then
        sudo pacman -Sy --noconfirm portaudio ffmpeg || fail "Failed to install system dependencies"
        success "System dependencies installed (pacman)"
    else
        warn "Could not detect package manager. Please install portaudio and ffmpeg manually."
    fi
fi

# ── Step 4: Create Python virtual environment ──
step "Setting up Python virtual environment"

if [[ -d "venv" && -f "venv/bin/activate" ]]; then
    success "Virtual environment already exists"
else
    info "Creating virtual environment..."
    "$PYTHON_CMD" -m venv venv || fail "Failed to create virtual environment.
    
    On Ubuntu/Debian, you may need: sudo apt install python3-venv"
    success "Virtual environment created"
fi

# Activate venv
source venv/bin/activate
success "Virtual environment activated"

# ── Step 5: Install Python dependencies ──
step "Installing Python packages"

info "Upgrading pip..."
pip install --upgrade pip --quiet 2>/dev/null

PACKAGES=(
    "edge-tts"
    "sounddevice"
    "soundfile"
    "numpy"
    "websockets"
    "aiohttp"
    "openai-whisper"
)

for pkg in "${PACKAGES[@]}"; do
    pkg_name=$(echo "$pkg" | tr '-' '_')
    if python -c "import importlib; importlib.import_module('$pkg_name')" 2>/dev/null; then
        success "$pkg already installed"
    else
        info "Installing $pkg..."
        pip install "$pkg" --quiet 2>&1 | tail -1 || fail "Failed to install $pkg"
        success "$pkg installed"
    fi
done

# Whisper import check (package name differs from import)
if python -c "import whisper" 2>/dev/null; then
    success "openai-whisper verified"
fi

# ── Step 6: Run setup wizard ──
step "Configuration"

if [[ -f "setup_wizard.py" ]]; then
    if [[ -f "config.json" ]]; then
        echo ""
        info "Existing configuration found (config.json)"
        read -p "   Re-run setup wizard? [y/N] " -n 1 -r
        echo ""
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            python setup_wizard.py
        else
            success "Keeping existing configuration"
        fi
    else
        echo ""
        info "Running first-time setup wizard..."
        echo ""
        python setup_wizard.py
    fi
else
    warn "setup_wizard.py not found — skipping configuration"
    info "You can configure manually by creating config.json"
fi

# ── Step 7: Make start.sh executable ──
if [[ -f "start.sh" ]]; then
    chmod +x start.sh
fi
chmod +x install.sh 2>/dev/null || true

# ── Done! ──
echo ""
echo -e "${GREEN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}${BOLD}  ✔  HERMES is installed and ready!${NC}"
echo -e "${GREEN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "  ${BOLD}To start Hermes:${NC}"
echo -e "    ${CYAN}cd $(pwd)${NC}"
echo -e "    ${CYAN}./start.sh${NC}"
echo ""
echo -e "  ${DIM}Hermes will open in your browser at http://127.0.0.1:8766${NC}"
echo ""

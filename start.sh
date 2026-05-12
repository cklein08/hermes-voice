#!/bin/bash
# ── HERMES Voice Assistant Launcher ──
cd "$(dirname "$0")"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  HERMES Voice Intelligence System"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Check for OpenRouter API key
if [ -z "$OPENROUTER_API_KEY" ]; then
  # Try to read from config
  if [ -f "$HOME/.hermes/hermes-voice/.env" ]; then
    export $(grep -v '^#' "$HOME/.hermes/hermes-voice/.env" | xargs)
  fi
fi

if [ -z "$OPENROUTER_API_KEY" ]; then
  echo ""
  echo "⚠  No OPENROUTER_API_KEY found."
  echo "   Set it via: export OPENROUTER_API_KEY=your_key"
  echo "   Or create .env file in this directory."
  echo ""
  read -p "Enter your OpenRouter API key (or press Enter to skip): " key
  if [ -n "$key" ]; then
    export OPENROUTER_API_KEY="$key"
    echo "OPENROUTER_API_KEY=$key" > .env
    echo "  Key saved to .env"
  fi
fi

echo ""
echo "Starting Hermes..."
echo ""

source venv/bin/activate
python3 server.py

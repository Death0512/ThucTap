#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════════
# Crawling Bot — Docker Entrypoint
# ══════════════════════════════════════════════════════════════════════════════

set -e

# Colors
RED='\033[0;31m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RESET='\033[0m'

echo ""
echo -e "${RED} ██████╗██████╗  █████╗ ██╗    ██╗██╗     ██╗███╗   ██╗ ██████╗     ██████╗  ██████╗ ████████╗${RESET}"
echo -e "${RED}██╔════╝██╔══██╗██╔══██╗██║    ██║██║     ██║████╗  ██║██╔════╝     ██╔══██╗██╔═══██╗╚══██╔══╝${RESET}"
echo -e "${RED}██║     ██████╔╝███████║██║ █╗ ██║██║     ██║██╔██╗ ██║██║  ███╗    ██████╔╝██║   ██║   ██║   ${RESET}"
echo -e "${RED}██║     ██╔══██╗██╔══██║██║███╗██║██║     ██║██║╚██╗██║██║   ██║    ██╔══██╗██║   ██║   ██║   ${RESET}"
echo -e "${RED}╚██████╗██║  ██║██║  ██║╚███╔███╔╝███████╗██║██║ ╚████║╚██████╔╝    ██████╔╝╚██████╔╝   ██║   ${RESET}"
echo -e "${RED} ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝ ╚══╝╚══╝ ╚══════╝╚═╝╚═╝  ╚═══╝ ╚═════╝     ╚═════╝  ╚═════╝    ╚═╝   ${RESET}"
echo ""
echo -e "${PINK}                        Facebook OSINT Platform — (Scrapling + Playwright)${RESET}"
echo ""


# ── Check LLM connectivity ──
echo "[1/3] Checking LLM API connection..."
if python3 -c "import llm_client; print('LLM OK' if llm_client.check_llm() else 'LLM FAIL')" 2>/dev/null; then
    echo "      LLM API reachable ✓"
else
    echo "      WARNING: LLM API not reachable"
    echo "      Check your OpenCode provider configuration"
fi

# ── Ensure runtime directories exist ──
echo "[2/3] Checking runtime directories..."
mkdir -p /app/reports /app/face_data /app/post_screenshots /app/status
echo "      Directories ready ✓"

# ── Check cookie file ──
echo "[3/3] Checking session cookies..."
if [ -f /app/fb_cookies.json ]; then
    echo "      fb_cookies.json found ✓"
else
    echo "      WARNING: fb_cookies.json not found"
    echo "      Use the Import Session Cookies tool in the web UI"
    echo "      Go to: http://localhost:5000/tools/import-cookies"
fi

echo ""
echo "══════════════════════════════════════════════════════"
echo "  Crawling Bot is running at http://localhost:5000"
echo "══════════════════════════════════════════════════════"
echo ""

# ── Start Flask app ──
exec /app/venv/bin/python /app/app.py

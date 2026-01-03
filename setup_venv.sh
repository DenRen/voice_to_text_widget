#!/bin/bash
# Voice-to-Text Quick Setup Script
# Creates virtual environment and installs all dependencies

set -e  # Exit on error

echo "======================================"
echo "Voice-to-Text Setup"
echo "======================================"
echo ""

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Check if system dependencies are installed
echo -e "${YELLOW}[1/5] Checking system dependencies...${NC}"
MISSING_DEPS=()

command -v python3 >/dev/null 2>&1 || MISSING_DEPS+=("python3")

if dpkg -l | grep -q python3-gi; then
    echo "  ✓ python3-gi installed"
else
    MISSING_DEPS+=("python3-gi")
fi

if dpkg -l | grep -q gir1.2-appindicator3-0.1; then
    echo "  ✓ gir1.2-appindicator3-0.1 installed"
else
    MISSING_DEPS+=("gir1.2-appindicator3-0.1")
fi

if dpkg -l | grep -q portaudio19-dev; then
    echo "  ✓ portaudio19-dev installed"
else
    MISSING_DEPS+=("portaudio19-dev")
fi

if command -v xclip >/dev/null 2>&1; then
    echo "  ✓ xclip installed"
else
    MISSING_DEPS+=("xclip")
fi

if [ ${#MISSING_DEPS[@]} -ne 0 ]; then
    echo ""
    echo -e "${RED}Missing system dependencies: ${MISSING_DEPS[*]}${NC}"
    echo ""
    echo "Please install them with:"
    echo -e "${YELLOW}sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-appindicator3-0.1 xclip portaudio19-dev${NC}"
    echo ""
    read -p "Do you want to install them now? [y/N] " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        sudo apt update
        sudo apt install -y python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-appindicator3-0.1 xclip portaudio19-dev
        echo -e "${GREEN}✓ System dependencies installed${NC}"
    else
        echo -e "${RED}Cannot proceed without system dependencies. Exiting.${NC}"
        exit 1
    fi
else
    echo -e "${GREEN}✓ All system dependencies are installed${NC}"
fi

echo ""
echo -e "${YELLOW}[2/5] Creating virtual environment...${NC}"
if [ -d "venv" ]; then
    echo -e "${YELLOW}  venv directory already exists. Removing it...${NC}"
    rm -rf venv
fi

python3 -m venv venv
echo -e "${GREEN}✓ Virtual environment created${NC}"

echo ""
echo -e "${YELLOW}[3/5] Activating virtual environment...${NC}"
source venv/bin/activate
echo -e "${GREEN}✓ Virtual environment activated${NC}"

echo ""
echo -e "${YELLOW}[4/5] Upgrading pip...${NC}"
pip install --upgrade pip -q
echo -e "${GREEN}✓ pip upgraded${NC}"

echo ""
echo -e "${YELLOW}[5/5] Installing Python dependencies...${NC}"
pip install groq pyaudio PyGObject-stubs -q
echo -e "${GREEN}✓ Python dependencies installed${NC}"

echo ""
echo "======================================"
echo -e "${GREEN}Setup Complete!${NC}"
echo "======================================"
echo ""
echo "Next steps:"
echo ""
echo "1. Activate the virtual environment:"
echo -e "   ${YELLOW}source venv/bin/activate${NC}"
echo ""
echo "2. Set your Groq API key:"
echo -e "   ${YELLOW}export GROQ_API_KEY=\"your-api-key-here\"${NC}"
echo "   Get it from: https://console.groq.com"
echo ""
echo "3. Run the application:"
echo -e "   ${YELLOW}python3 voice_tray.py${NC}"
echo ""
echo "4. Bind a hotkey in system settings:"
echo "   Command: kill -SIGUSR1 \$(pgrep -f voice_tray.py)"
echo "   Suggested key: Ctrl+Shift+Space"
echo ""
echo "For more information, see README.md"
echo ""

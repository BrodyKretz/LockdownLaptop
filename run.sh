#!/bin/bash
set -e
cd "$(dirname "$0")"

# Install deps if missing
if ! python3 -c "import pynput, PIL, mss, cv2" 2>/dev/null; then
    echo "Installing dependencies..."
    pip3 install -r requirements.txt
fi

echo "Starting LockdownLaptop..."
echo ""
echo "NOTE: On first run macOS will ask for:"
echo "  • Accessibility (Input Monitoring) — needed to suppress keys"
echo "  • Camera — needed for Snitch Cam feature"
echo ""

python3 lockdown.py

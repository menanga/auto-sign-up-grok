#!/bin/bash
set -e

# Auto-detect if DISPLAY is missing and start Xvfb
if [ -z "$DISPLAY" ]; then
    echo "No DISPLAY found, starting Xvfb..."
    Xvfb :99 -screen 0 1280x1024x24 &
    export DISPLAY=:99
    sleep 2
fi

# Diagnostic: verify environment
echo "=== Environment Diagnostics ==="
echo "DISPLAY: $DISPLAY"
echo "Chrome binary: $(which google-chrome || which chromium || echo 'not in PATH')"
echo "Python version: $(python --version)"
echo "nodriver version: $(python -c 'import nodriver; print(nodriver.__version__)' 2>/dev/null || echo 'not installed')"
echo "=============================="
echo ""

# Run the nodriver script with all arguments
exec python grok-signup-nodriver-gmail.py "$@"

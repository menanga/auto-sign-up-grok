#!/bin/bash
set -e

# Auto-detect if DISPLAY is missing and start Xvfb
if [ -z "$DISPLAY" ]; then
    echo "No DISPLAY found, starting Xvfb..."
    Xvfb :99 -screen 0 1280x1024x24 &
    export DISPLAY=:99
    sleep 2
fi

# Run the Python script with all arguments
exec python grok-signup-playwright-gmail.py "$@"

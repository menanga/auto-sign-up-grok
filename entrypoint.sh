#!/bin/bash
set -e

# Auto-detect if DISPLAY is missing and start Xvfb
if [ -z "$DISPLAY" ]; then
    echo "No DISPLAY found, starting Xvfb..."
    Xvfb :99 -screen 0 1280x1024x24 &
    export DISPLAY=:99
    sleep 2
fi

# Diagnostic: verify turnstilePatch extension exists
echo "=== Environment Diagnostics ==="
echo "DISPLAY: $DISPLAY"
echo "Chrome binary: $(which google-chrome || which chromium || echo 'not in PATH')"
echo "Python version: $(python --version)"
echo "Playwright version: $(python -c 'import playwright; print(playwright.__version__)' 2>/dev/null || echo 'not installed')"

if [ -d "turnstilePatch" ]; then
    echo "✓ turnstilePatch directory exists"
    echo "  Files:"
    ls -lh turnstilePatch/
    if [ -f "turnstilePatch/manifest.json" ]; then
        echo "  manifest.json:"
        cat turnstilePatch/manifest.json | head -10
    else
        echo "  ✗ manifest.json missing!"
    fi
else
    echo "✗ turnstilePatch directory NOT FOUND"
fi

echo "=============================="
echo ""

# Run the Python script with all arguments
exec python grok-signup-playwright-gmail.py "$@"

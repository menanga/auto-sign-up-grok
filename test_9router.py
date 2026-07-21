#!/usr/bin/env python3
"""Test 9router add function with latest account from sso.txt"""
import json
import sys
from pathlib import Path

# Add parent dir to path to import from main script
sys.path.insert(0, str(Path(__file__).parent))

from grok_signup_playwright_gmail import add_to_router_single

# Read latest account
sso_file = Path('sso.txt')
if not sso_file.exists():
    print("No sso.txt found")
    sys.exit(1)

accounts = []
for line in sso_file.read_text().strip().splitlines():
    try:
        accounts.append(json.loads(line))
    except:
        pass

if not accounts:
    print("No valid accounts in sso.txt")
    sys.exit(1)

# Test with latest
latest = accounts[-1]
print(f"Testing 9router add for: {latest['email']}")
print(f"Cookies count: {len(latest.get('sso_cookies', []))}")

result = add_to_router_single(latest)
print(f"\nResult: {result}")

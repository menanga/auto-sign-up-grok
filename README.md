<div align="center">

# 🚀 Auto Sign-Up Grok + 9Router

### Automated Grok (x.ai) Account Registration with OAuth Device Flow Integration

**Playwright · Gmail IMAP · Turnstile Bypass · Auto-Import to 9Router**

---

![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white)
![Playwright](https://img.shields.io/badge/Playwright-latest-green?logo=playwright&logoColor=white)
![Chrome](https://img.shields.io/badge/Chrome-Stable-orange?logo=googlechrome&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Linux-lightgrey?logo=linux&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-yellow)

</div>

---

## 📋 Table of Contents

- [✨ Features](#-features)
- [📦 Prerequisites](#-prerequisites)
- [🔧 Installation](#-installation)
- [⚙️ Configuration](#️-configuration)
  - [Gmail IMAP Setup](#gmail-imap-setup)
  - [9Router Setup](#9router-setup)
- [🎯 Usage](#-usage)
- [📁 Output](#-output)
- [🔄 Flow](#-flow)
- [🖥️ UI Preview](#️-ui-preview)
- [🚨 Troubleshooting](#-troubleshooting)
- [📝 Notes](#-notes)

---

## ✨ Features

| Feature | Status |
|---------|--------|
| 🤖 Auto-register Grok (x.ai) accounts | ✅ |
| 📧 Gmail IMAP integration (alias support) | ✅ |
| 🔢 Auto OTP verification + email deletion | ✅ |
| 🛡️ Turnstile bypass (extension-based) | ✅ |
| 🔄 In-browser turnstile retry (3 attempts) | ✅ |
| 🔐 OAuth device flow integration | ✅ |
| 🔗 Auto-import to 9Router with guaranteed retry | ✅ |
| 📊 Batch registration with beautiful logging | ✅ |
| ♻️ Infinite mode support | ✅ |
| 📈 Real-time import counter | ✅ |

---

## 📦 Prerequisites

| Tool | Version | Check |
|------|---------|-------|
| Python | 3.11+ | `python3 --version` |
| Google Chrome | Stable | `google-chrome --version` |
| Git | any | `git --version` |

### System Requirements

- **OS**: Linux (Ubuntu 20.04+, Debian 11+) or WSL2
- **RAM**: 2GB minimum (4GB recommended for batch processing)
- **Network**: Stable internet connection
- **Gmail Account**: With IMAP enabled + App Password generated

---

## 🔧 Installation

### 1. Clone Repository

```bash
git clone https://github.com/dzDev3/Auto-sign-up-grok-dezz.git
cd Auto-sign-up-grok-dezz
```

### 2. Install System Dependencies

#### Ubuntu/Debian
```bash
sudo apt update
sudo apt install -y python3.11 python3.11-venv google-chrome-stable
```

#### Fedora/RHEL
```bash
sudo dnf install -y python3.11 google-chrome-stable
```

### 3. Setup Python Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate  # or `.venv/bin/activate` on Linux
```

### 4. Install Python Dependencies

```bash
pip install --upgrade pip
pip install playwright curl_cffi python-dotenv
playwright install chrome
```

### 5. Verify Installation

```bash
python -c "import playwright; import curl_cffi; print('✓ Dependencies OK')"
ls turnstilePatch/  # Should show: manifest.json  script.js
```

---

## ⚙️ Configuration

### 1. Create Configuration File

```bash
cp .env.example .env
```

### 2. Edit `.env`

```ini
# ── 9Router API ──────────────────────────────────
ROUTER9_URL=https://your-9router.example
ROUTER9_PASS=your_9router_password

# ── Gmail IMAP (for OTP verification) ────────────
# Use App Password, NOT regular Gmail password
# Enable IMAP in Gmail settings first
GMAIL_USER=yourgmail@gmail.com
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
GMAIL_DOMAINS=youralias1.com,youralias2.com,gmail.com

# ── Chrome Binary ─────────────────────────────────
CHROME_BIN=/usr/bin/google-chrome

# ── Grok Account ──────────────────────────────────
# Min 16 characters — x.ai rejects weak passwords
PASSWORD=YourStrongPassword123!@#

# ── Runner Config ─────────────────────────────────
MAX_ACCOUNTS=0          # 0 = infinite loop
BATCH_SIZE=1            # Accounts per batch
PAUSE_SECONDS=10        # Delay between batches
DELAY_SECONDS=5         # Delay between accounts
MAX_ACCOUNT_RETRIES=3   # Max retries per account
AUTO_ADD=true           # Auto-import to 9Router
```

---

## Gmail IMAP Setup

### Step 1: Enable IMAP in Gmail

1. Open Gmail → Click **Settings** (gear icon) → **See all settings**
2. Go to **Forwarding and POP/IMAP** tab
3. Under **IMAP access**, select **Enable IMAP**
4. Click **Save Changes**

### Step 2: Generate App Password

1. Go to [Google Account Security](https://myaccount.google.com/security)
2. Enable **2-Step Verification** (required for App Passwords)
3. Go to [App Passwords](https://myaccount.google.com/apppasswords)
4. Select **Mail** and **Other (Custom name)** → Enter "Grok Signup"
5. Click **Generate**
6. Copy the 16-character password (format: `xxxx xxxx xxxx xxxx`)

### Step 3: Update `.env`

```ini
GMAIL_USER=yourgmail@gmail.com
GMAIL_APP_PASSWORD=abcd efgh ijkl mnop  # Paste the 16-char App Password
```

### Step 4: Configure Alias Domains

Gmail supports `+` aliases and custom domain aliases:

```ini
# Option 1: Gmail + aliases (built-in)
GMAIL_DOMAINS=gmail.com

# Option 2: Custom domain aliases (if you own domains)
GMAIL_DOMAINS=yourdomain1.com,yourdomain2.com,gmail.com
```

**How it works:**
- Script generates random email like `abcde.fghij.1234@yourdomain.com`
- Gmail receives at your main address
- OTP extracted, email deleted automatically

---

## 9Router Setup

### Prerequisites

- 9Router instance running at `ROUTER9_URL`
- Admin password for API access

### API Endpoints Used

```
POST /api/auth/login           → Authenticate
GET  /api/oauth/grok-cli/device-code → Get OAuth device code
POST /api/oauth/grok-cli/poll        → Poll for completion
GET  /api/providers                   → List existing accounts
```

### Configuration

```ini
ROUTER9_URL=https://xapi.your-domain.com
ROUTER9_PASS=your_admin_password
```

### Test 9Router Connection

```bash
curl -X POST https://xapi.your-domain.com/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"password":"your_admin_password"}'
```

Expected response:
```json
{"success": true}
```

---

## 🎯 Usage

### Basic Usage

```bash
# Activate virtual environment
source .venv/bin/activate

# Run with auto-import to 9Router
python grok-signup-playwright-gmail.py --auto-add
```

### Advanced Usage

```bash
# Infinite mode (MAX_ACCOUNTS=0 in .env)
python grok-signup-playwright-gmail.py --auto-add

# Custom batch size (via .env)
# Edit .env: BATCH_SIZE=5
python grok-signup-playwright-gmail.py --auto-add

# Fast mode (reduce delays via .env)
# Edit .env: PAUSE_SECONDS=5, DELAY_SECONDS=2
python grok-signup-playwright-gmail.py --auto-add
```

### What Happens During Execution

1. **Login to 9Router** → Get auth token
2. **Request device code** → Generates OAuth URL with user_code
3. **Open browser** → Navigate to signup URL with OAuth redirect
4. **Generate Gmail alias** → Random email like `xxxxx.yyyyy.zzzz@domain.com`
5. **Submit email** → Wait for OTP input
6. **Poll Gmail IMAP** → Extract OTP from email subject/body
7. **Delete OTP email** → Clean up inbox
8. **Submit OTP** → Verify code
9. **Fill profile form** → Auto-generate name from email
10. **Solve Turnstile** → Extension bypasses challenge (10s timeout, 3 retries)
11. **Submit signup** → Auto-redirect to OAuth approval page
12. **Click Continue/Allow** → Authorize Grok Build access
13. **Close browser** → Free resources
14. **Poll 9Router API** → Import account (20 retries, guaranteed delivery)
15. **Save to files** → `sso.txt` + `~/.grok/auth.json`

---

## 📁 Output

### `sso.txt` — JSON Lines Format

```json
{
  "email": "xxxxx.yyyyy.zzzz@domain.com",
  "password": "YourStrongPassword123!@#",
  "code": "ABC123",
  "sso_cookies": [],
  "final_url": "",
  "timestamp": 1721535200
}
```

### `~/.grok/auth.json` — Grok CLI Format

```json
{
  "accounts": [
    {
      "email": "xxxxx.yyyyy.zzzz@domain.com",
      "token": null
    }
  ]
}
```

### Check Results

```bash
# Total accounts created
wc -l sso.txt

# Extract email list
grep -oE '"email": "[^"]+"' sso.txt | sed 's/"email": "//;s/"//' | sort

# Domain breakdown
grep -oE '@[^"]+' sso.txt | sort | uniq -c | sort -rn
```

---

## 🔄 Flow

### Complete Registration + Import Flow

```
┌─────────────────────────────────────────────────────────────────┐
│  1. Login 9Router → Extract auth_token from Set-Cookie          │
│           ↓                                                       │
│  2. GET /device-code → device_code, codeVerifier, user_code     │
│           ↓                                                       │
│  3. Build signup URL with OAuth redirect:                        │
│     https://accounts.x.ai/sign-up?redirect=oauth2-provider       │
│     &return_to=/oauth2/device?user_code=XXXX-XXXX               │
│           ↓                                                       │
│  4. Open browser → Navigate to signup URL                        │
│           ↓                                                       │
│  5. Accept cookies → Click "Sign up with email"                 │
│           ↓                                                       │
│  6. Generate Gmail alias → Fill email → Submit                   │
│           ↓                                                       │
│  7. Poll Gmail IMAP (120s timeout)                              │
│     - Extract OTP from Subject or Body                           │
│     - Delete email after extraction                              │
│           ↓                                                       │
│  8. Submit OTP → Wait for profile form                          │
│           ↓                                                       │
│  9. Auto-fill givenName, familyName, password                   │
│           ↓                                                       │
│ 10. Solve Turnstile (10s, max 3 retries)                        │
│     - If timeout: Click "Go back"                                │
│     - Re-input email → Get fresh OTP → Retry                    │
│           ↓                                                       │
│ 11. Submit "Complete sign up"                                    │
│           ↓                                                       │
│ 12. Auto-redirect to OAuth approval page                         │
│     (URL contains user_code from step 2)                        │
│           ↓                                                       │
│ 13. Accept cookies (if banner appears)                          │
│           ↓                                                       │
│ 14. Click "Continue" → Click "Allow"                            │
│           ↓                                                       │
│ 15. Close browser immediately                                    │
│           ↓                                                       │
│ 16. Poll 9Router /poll API (20 retries × 5s = 100s max)        │
│     - Retry on network errors                                    │
│     - Retry on non-pending errors                               │
│     - Guaranteed delivery after account creation                │
│           ↓                                                       │
│ 17. Save to sso.txt + ~/.grok/auth.json                         │
│           ↓                                                       │
│ 18. Display batch summary + total imported counter              │
└─────────────────────────────────────────────────────────────────┘
```

### Turnstile Retry Mechanism

```
┌─────────────────────────────────────────────────┐
│  Attempt 1: Wait 10s for Turnstile token        │
│             ↓                                     │
│         Success? → Continue                      │
│             ↓ Fail                               │
│  Click "Go back" → Re-input same email          │
│             ↓                                     │
│  Clear seen IDs → Poll Gmail for fresh OTP      │
│             ↓                                     │
│  Submit new OTP → Re-fill form                  │
│             ↓                                     │
│  Attempt 2: Wait 10s for Turnstile token        │
│             ↓                                     │
│         Success? → Continue                      │
│             ↓ Fail                               │
│  Repeat (max 3 attempts)                        │
│             ↓                                     │
│  All failed? → Raise error                      │
└─────────────────────────────────────────────────┘
```

---

## 🖥️ UI Preview

### Beautiful Logging Output

```
╔════════════════════════════════════════════════════════════════════╗
║ GROK SIGNUP + 9ROUTER AUTO-IMPORT                                  ║
╠════════════════════════════════════════════════════════════════════╣
║ Mode: INFINITE
║ Batch Size: 1
║ Chrome: /usr/bin/google-chrome
║ Auto-Import: YES
╚════════════════════════════════════════════════════════════════════╝

┌─ BATCH #1 ──────────────────────────────────────────────────────
│ [1] Starting account creation...
  ✓ device code: DKZW-KPKD
  ✓ signup URL: https://accounts.x.ai/sign-up?redirect=oauth2-provider&return_to=%2Foauth2%2Fdevice%3Fuser_code%3DDKZW-KPKD
  ✓ page loaded
  ✓ email form
  → abcde.fghij.1234@yourdomain.com
  ✓ email submitted
  → found 1 emails for abcde.fghij.1234@yourdomain.com
  → Email: From=SpaceXAI <noreply@x.ai>, Subject=Your verification code is ABC123
  ✓ Extracted OTP: ABC123 from SUBJECT
  ✓ deleted OTP email
  ✓ OTP: ABC123
  ✓ OTP verified
  ✓ form filled
  → solving turnstile (attempt 1/3)...
  ✓ turnstile solved
  ✓ submitted
  → waiting for OAuth page...
  ✓ OAuth page loaded
  ✓ accepted cookies
  ✓ clicked Continue
  ✓ clicked Allow
  ✓ closing browser...
  → polling 9router (guaranteed retry)...
  ✓ 9router import success (attempt 1/20)
  ✓ saved → sso.txt
  ✓ saved → /home/user/.grok/auth.json
│ ✓ [1] abcde.fghij.1234@yourdomain.com → imported in 42.3s
└──────────────────────────────────────────────────────────────────

■ Batch Summary:
  ├─ Imported: 1/1
  ├─ Failed: 0
  └─ Total Imported (all batches): 1

■ Overall Stats:
  ├─ Total Attempts: 1
  ├─ Successful: 1
  ├─ Failed: 0
  └─ Success Rate: 100%

→ Sleeping 10s before next batch...
```

### Final Report

```
╔════════════════════════════════════════════════════════════════════╗
║ FINAL REPORT                                                        ║
╠════════════════════════════════════════════════════════════════════╣
║ Total Imported to 9router: 42
║ Success: 42  |  Failed: 3  |  Total: 45
╚════════════════════════════════════════════════════════════════════╝
```

---

## 🚨 Troubleshooting

### 🔐 "OTP timeout 120s"

**Cause:** Gmail IMAP not receiving emails or wrong credentials

**Fix:**
```bash
# Test Gmail IMAP connection
python3 << 'EOF'
import imaplib
mail = imaplib.IMAP4_SSL('imap.gmail.com')
mail.login('yourgmail@gmail.com', 'your_app_password')
mail.select('inbox')
print("✓ IMAP connection OK")
mail.logout()
EOF
```

- Verify `GMAIL_USER` and `GMAIL_APP_PASSWORD` in `.env`
- Check IMAP is enabled in Gmail settings
- Regenerate App Password if needed
- Check Gmail quota (not over storage limit)

### 🛡️ "Turnstile failed after 3 attempts"

**Cause:** Extension not loaded or browser automation detected

**Fix:**
- Verify `turnstilePatch/` folder exists with `script.js` and `manifest.json`
- Check Chrome version: `google-chrome --version` (must be stable, not Chromium)
- Restart script (Turnstile difficulty varies)
- Reduce `BATCH_SIZE` to 1 (reduces detection)

### 🔗 "9router login failed"

**Cause:** Wrong URL or password

**Fix:**
```bash
# Test 9Router API
curl -X POST $ROUTER9_URL/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"password":"your_password"}' \
  -v
```

- Check `ROUTER9_URL` format (https://domain.com, no trailing slash)
- Verify `ROUTER9_PASS` is correct
- Check 9Router service is running

### 🚫 "curl timeout after 60s"

**Cause:** Network issue or 9Router API overloaded

**Fix:**
- Script auto-retries 20 times with 5s interval
- Check 9Router logs for errors
- Verify network connectivity: `ping xapi.your-domain.com`
- Increase timeout if needed (already set to 60s)

### 📧 "Gmail IMAP: [AUTHENTICATIONFAILED]"

**Cause:** Wrong App Password or IMAP disabled

**Fix:**
1. Regenerate App Password at https://myaccount.google.com/apppasswords
2. Enable IMAP in Gmail Settings → Forwarding and POP/IMAP
3. Use App Password (16 chars), NOT regular Gmail password
4. Remove spaces from App Password in `.env`

### 🔒 "Password too weak"

**Cause:** Password < 16 characters

**Fix:**
```ini
# Update .env with strong password
PASSWORD=MyStrongPassword123!@#$
```

- Min 16 characters
- Mix: uppercase + lowercase + numbers + symbols
- x.ai enforces strong password policy

### ⚠️ "Account created but not imported"

**Cause:** Poll timeout or network error after signup

**Fix:**
- Account IS created and saved in `sso.txt`
- Manually import: Check 9Router logs for device_code
- Re-run script will create new account (old one saved)
- Script guarantees 20 retry attempts (100s total)

---

## 📝 Notes

| Item | Detail |
|------|--------|
| ⏱️ Speed | ~40-50s per account (signup + OAuth + import) |
| 📧 Gmail Alias | Supports `+` alias and custom domain forwarding |
| 🔄 OTP Email | Auto-deleted after extraction (keeps inbox clean) |
| 🛡️ Turnstile | 10s timeout × 3 retries = 30s max, with in-browser retry |
| 🔗 9Router | Guaranteed import with 20 retries (100s timeout) |
| 📝 Output | `sso.txt` (append mode) + `~/.grok/auth.json` (Grok CLI format) |
| 🚀 Batch Mode | Configurable via `BATCH_SIZE`, `PAUSE_SECONDS`, `DELAY_SECONDS` |
| ♻️ Infinite Loop | Set `MAX_ACCOUNTS=0` for continuous registration |
| 📊 Counter | Real-time total imported count after each batch |
| 🌐 Chrome | Google Chrome stable (not Chromium) — required for extension |

---

## 🔐 Security Notes

- **App Password**: Never commit `.env` to git (already in `.gitignore`)
- **SSO Cookies**: Stored locally in `sso.txt` — protect this file
- **9Router Password**: Use strong password, rotate regularly
- **Gmail Access**: App Password scope limited to IMAP only

---

## 📚 Related Resources

- [Gmail IMAP Setup Guide](https://support.google.com/mail/answer/7126229)
- [Google App Passwords](https://support.google.com/accounts/answer/185833)
- [Playwright Documentation](https://playwright.dev/python/)
- [Grok (x.ai) Official Site](https://x.ai/)

---

<div align="center">

**⚠️ Disclaimer: For educational and automation purposes only. Use responsibly.**

**Made with ❤️ by dzDev**

</div>

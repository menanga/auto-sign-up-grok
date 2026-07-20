<div align="center">

# 🚀 Auto Sign-Up Grok Dezz

### Automated Grok (x.ai) Account Registration + 9Router Integration

**Playwright · Chrome · Xvfb · Turnstile Bypass · OAuth Device Flow**

---

![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white)
![Playwright](https://img.shields.io/badge/Playwright-latest-green?logo=playwright&logoColor=white)
![Chrome](https://img.shields.io/badge/Chrome-Stable-orange?logo=googlechrome&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Linux-lightgrey?logo=linux&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-yellow)

</div>

---

## 📋 Daftar Isi

- [🤖 AI Setup Guide](#-ai-setup-guide)
- [✨ Fitur](#-fitur)
- [📦 Prasyarat](#-prasyarat)
- [🔧 Install](#-install)
- [⚙️ Konfigurasi](#️-konfigurasi)
- [🎯 Penggunaan](#-penggunaan)
- [📁 Output](#-output)
- [🔄 Flow](#-flow)
- [🖥️ Tampilan UI](#️-tampilan-ui)
- [🚨 Troubleshooting](#-troubleshooting)
- [📝 Notes](#-notes)

---

## 🤖 AI Setup Guide

> **Bagian ini khusus untuk AI assistant (Claude, GPT, Cursor, dll).**
> Jika user minta bantuan setup project ini, ikuti panduan di bawah. User tidak perlu tanya-tanya ke author.

### Tugas AI: Setup end-to-end untuk user

Ikuti langkah-langkah berurutan. Setiap langkah ada verifikasi. Kalau ada yang gagal, AI harus bisa diagnose + fix otomatis sebelum lapor ke user.

#### 1. Detect Environment

```bash
# Cek OS
uname -m              # x86_64 / aarch64 (Linux/macOS)
cat /etc/os-release   # distro (Linux)

# Windows PowerShell:
# $env:OS              # Windows_NT
# [System.Environment]::OSVersion

# Cek tools (Linux/macOS)
python3 --version     # butuh 3.11+
google-chrome --version 2>/dev/null || google-chrome-stable --version 2>/dev/null
which xvfb-run || echo "XVFB_MISSING"
git --version

# Windows (PowerShell)
python --version      # butuh 3.11+
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --version
git --version
```

**Diagnose AI:**
- Python < 3.11 → install: `sudo apt install python3.11 python3.11-venv` (Ubuntu) atau pakai pyenv. Windows: install dari python.org.
- Chrome missing (Linux) → install: `wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb && sudo dpkg -i google-chrome-stable_current_amd64.deb && sudo apt -f install -y`
- Chrome missing (Windows) → install dari https://www.google.com/chrome/
- Xvfb missing → `sudo apt install -y xvfb` (Linux only — Windows gak perlu)

#### 2. Clone + Venv

```bash
git clone https://github.com/dzDev3/Auto-sign-up-grok-dezz.git
cd Auto-sign-up-grok-dezz

# Linux/macOS
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install playwright curl_cffi
.venv/bin/playwright install chrome

# Windows (PowerShell)
python -m venv .venv
.venv\Scripts\pip install --upgrade pip
.venv\Scripts\pip install playwright curl_cffi
.venv\Scripts\playwright install chrome
```

**Verifikasi:**
```bash
# Linux/macOS
.venv/bin/python -c "import playwright; import curl_cffi; print('deps OK')"
# Windows
.venv\Scripts\python -c "import playwright; import curl_cffi; print('deps OK')"
```

#### 3. Config `.env`

```bash
cp .env.example .env
```

AI harus tanya user 3 hal ini (wajib), lalu tulis ke `.env`:

| Field | Tanya ke user | Contoh |
|-------|---------------|--------|
| `MAILLDEZ_URL` | "URL temp mail API Anda? (MAILLDEZ-compatible: GET /api/session, POST /api/inboxes, GET /api/inboxes/{addr}/messages)" | `https://mail.example.com` |
| `MAILLDEZ_DOMAINS` | "Domain temp mail Anda? (comma-separated)" | `domain1.com,domain2.com` |
| `PASSWORD` | "Password untuk akun Grok yang akan dibuat? Min 16 char, campur huruf+angka+simbol" | `MyStrongPass123!@` |

**Opsional** (kalau user punya 9Router):
- `ROUTER9_URL` + `ROUTER9_PASS` — kalau user mau auto-add akun ke 9Router

**Validasi `.env`:**
```bash
# AI: pastikan tidak ada placeholder "your-" atau "change-me" di MAILLDEZ_URL, MAILLDEZ_DOMAINS, PASSWORD
grep -E "your-|change-me|example\.com" .env && echo "INCOMPLETE_CONFIG" || echo "CONFIG_OK"
```

#### 4. Test Turnstile Patch

```bash
.venv/bin/python -c "
from grok_signup import unlock_turnstile
ext_path = unlock_turnstile()
print('TURNSTILE_OK' if ext_path else 'TURNSTILE_FAIL')
"
```

**Kalau gagal:**
- `TURNSTILE_FAIL` → file `turnstilePatch/script.js` atau `manifest.json` gak ada. Cek: `ls turnstilePatch/`

#### 5. Test Temp Mail

```bash
.venv/bin/python -c "
import curl_cffi.requests as creq, json
url = open('.env').read()
mail_url = [l.split('=',1)[1].strip() for l in url.splitlines() if l.startswith('MAILLDEZ_URL=')][0]
domains = [l.split('=',1)[1].strip() for l in url.splitlines() if l.startswith('MAILLDEZ_DOMAINS=')][0].split(',')
r = creq.get(f'{mail_url}/api/session', timeout=10)
print('session:', r.status_code)
sid = r.json().get('sessionId','')
r2 = creq.post(f'{mail_url}/api/inboxes', json={'domain': domains[0]}, headers={'x-session-id': sid}, timeout=10)
print('inbox:', r2.status_code, r2.json().get('address',''))
print('MAIL_OK' if r2.status_code == 200 else 'MAIL_FAIL')
"
```

**Kalau gagal:**
- `session: 000` → URL salah / API down. AI cek: `curl -v $MAILLDEZ_URL/api/session`
- `MAIL_FAIL` → domain tidak valid atau API reject. AI coba domain lain dari list.

#### 6. Run Test (1 akun)

```bash
# Linux (wajib xvfb — headless deteksi bot)
xvfb-run -a .venv/bin/python grok-signup.py 1

# Windows (gak butuh xvfb — ada display asli)
.venv\Scripts\python grok-signup.py 1
```

**Verifikasi sukses:**
- Output: `[09] done SUCCESS`
- File `sso.txt` muncul dengan 1 entry

**Kalau gagal, AI diagnose:**

| Error | Penyebab | Fix AI |
|-------|----------|--------|
| `turnstile load: missing` | File patch gak ada | Cek `ls turnstilePatch/` (script.js + manifest.json) |
| `Password too weak` | PASSWORD < 16 char | Edit `.env`, buat password 16+ char |
| `OTP gak masuk 120s` | Temp mail API bermasalah | Ulang langkah 5, cek domain |
| `Turnstile gak solved 40s` | Extension gak load / platform mismatch | Cek `turnstilePatch/script.js` + `manifest.json` ada. Windows: pastikan Chrome (bukan Chromium) |
| `Cloudflare Attention Required` | IP diblok / headless | Linux: pastikan pakai `xvfb-run`. Windows: jangan pakai `--headless` |
| `ctx undefined` / scope error | Script bug | Lapor ke author dengan full traceback |
| `Execution context destroyed` | Navigasi saat evaluate | Normal, script sudah handle |

#### 7. Selesai

```bash
# Cek hasil
wc -l sso.txt
grep -oE '"email": "[^"]+"' sso.txt | wc -l
```

---

### Quick Reference untuk AI

```
Repo:        github.com/dzDev3/Auto-sign-up-grok-dezz
Script:      grok-signup.py
Config:      .env (dari .env.example)
Output:      sso.txt (JSON lines)

Run (Linux):   xvfb-run -a .venv/bin/python grok-signup.py <count>
Run (Windows): .venv\Scripts\python grok-signup.py <count>
Add router:    sama saja + --router [N]

Turnstile:   AUTO (plaintext patch, load as Chrome extension)
Temp mail:   USER-PROVIDED (MAILLDEZ-compatible API)
9Router:     OPTIONAL (user-provided)

Yang user HARUS sediakan:
  1. Temp mail API (MAILLDEZ-compatible)
  2. Password untuk akun Grok (min 16 char)
  3. Chrome + Python 3.11+ (Linux: +Xvfb)

Yang user TIDAK perlu:
  - Turnstile patch (plaintext, included)
  - Author intervention
```

---

## ✨ Fitur

| Fitur | Status |
|-------|--------|
| 🤖 Auto-register akun Grok (x.ai) | ✅ |
| 📧 Temp mail integration (MAILLDEZ) | ✅ |
| 🔢 Auto OTP verification | ✅ |
| 🛡️ Turnstile bypass (Chrome extension) | ✅ |
| 🎲 Domain rotation (round-robin) | ✅ |
| 🔐 SSO cookies save | ✅ |
| 🔗 9Router OAuth device flow integration | ✅ |
| 📊 Dashboard UI (progress bar, logs, stats) | ✅ |
| 📦 Batch registration | ✅ |
| ♻️ Add existing accounts to 9Router | ✅ |

---

## 📦 Prasyarat

| Tool | Versi | Cek |
|------|-------|-----|
| Python | 3.11+ | `python3 --version` |
| Google Chrome | Stable | `google-chrome --version` |
| Xvfb | any | `sudo apt install xvfb` |
| Git | any | `git --version` |

> ⚠️ **Headless mode tidak support** — x.ai mendeteksi bot. Pakai Xvfb virtual display.

---

## 🔧 Install

```bash
git clone https://github.com/dzDev3/Auto-sign-up-grok-dezz.git
cd Auto-sign-up-grok-dezz

# Virtual environment + dependencies
python3 -m venv .venv
.venv/bin/pip install playwright curl_cffi

# Install Chrome untuk Playwright
.venv/bin/playwright install chrome
```

---

## ⚙️ Konfigurasi

```bash
cp .env.example .env
```

Edit `.env`:

```ini
# ── 9Router ──────────────────────────────────
ROUTER9_URL=https://your-9router.example
ROUTER9_PASS=your_9router_password

# ── Temp Mail (MAILLDEZ-compatible) ──────────
# API: GET /api/session, POST /api/inboxes {domain}, GET /api/inboxes/{addr}/messages
MAILLDEZ_URL=https://your-mail-api.example
MAILLDEZ_DOMAINS=domain1.com,domain2.com,domain3.com

# ── Akun Grok ────────────────────────────────────
# Min 16 char — x.ai reject password pendek
PASSWORD=YourStrongPassword123
```

---

## 🎯 Penggunaan

### Register Akun Baru

```bash
# Register 1 akun
xvfb-run -a .venv/bin/python grok-signup.py 1

# Register batch 10 akun
xvfb-run -a .venv/bin/python grok-signup.py 10
```

> Setelah selesai, muncul prompt:
> ```
> ? Add 10 akun ke 9router? [y/N]
> ```
> Ketik `y` untuk auto-add ke 9Router, atau `N` untuk skip.

### Add Akun Existing ke 9Router

```bash
# Add semua akun dari sso.txt
xvfb-run -a .venv/bin/python grok-signup.py --router

# Add 10 akun terakhir saja
xvfb-run -a .venv/bin/python grok-signup.py --router 10
```

> Akun yang sudah ada di 9Router otomatis di-skip (no duplicates).

---

## 📁 Output

`sso.txt` — JSON lines format, 1 baris per akun:

```json
{
  "email": "user@domain.com",
  "password": "YourStrongPassword123",
  "code": "ABC123",
  "sso_cookies": [{"name": "sso", "value": "...", "domain": ".x.ai"}],
  "final_url": "https://grok.com/",
  "timestamp": 1720000000
}
```

Cek hasil:

```bash
# Total akun
wc -l sso.txt

# Domain breakdown
grep -oE '"email": "[^"]+@[^"]+"' sso.txt | grep -oE '@[^"]+' | sort | uniq -c | sort -rn
```

---

## 🔄 Flow

### Register Flow

```
┌─────────────────────────────────────────────────────┐
│  1. Buka accounts.x.ai/sign-up                      │
│           ↓                                          │
│  2. Create temp email (MAILLDEZ API)                │
│     Domain di-rotate round-robin                    │
│           ↓                                          │
│  3. Isi email → Enter → tunggu OTP                  │
│           ↓                                          │
│  4. Polling MAILLDEZ → extract OTP dari subject     │
│           ↓                                          │
│  5. Isi OTP → Enter → halaman nama + password       │
│           ↓                                          │
│  6. Isi givenName + familyName + password           │
│           ↓                                          │
│  7. Solve Turnstile (turnstilePatch extension)      │
│           ↓                                          │
│  8. Submit → redirect ke grok.com                   │
│           ↓                                          │
│  9. Save SSO cookies → sso.txt                      │
└─────────────────────────────────────────────────────┘
```

### 9Router Integration Flow

```
┌─────────────────────────────────────────────────────┐
│  1. Login 9Router (POST /api/auth/login)            │
│           ↓                                          │
│  2. Cek existing providers (skip duplicates)        │
│           ↓                                          │
│  3. Inject SSO cookies ke browser context            │
│           ↓                                          │
│  4. GET device-code → user_code + verify URL       │
│           ↓                                          │
│  5. Buka verify URL → klik [Continue]               │
│           ↓                                          │
│  6. Consent page → klik [Allow]                     │
│           ↓                                          │
│  7. Poll 9Router sampai success: true               │
└─────────────────────────────────────────────────────┘
```

---

## 🖥️ Tampilan UI

### Live Demo — Batch 8

![8 akun SUCCESS + 9Router add 8/8](assets/ui-demo.jpg)

### Live Demo — Batch 500 (470/470 added to 9Router)

![Batch 500 — 94% health, 470 akun ke 9Router](assets/ui-batch500.jpg)

### ASCII Preview

```
 ─── [ GROK SIGNUP RUNNER ] ──────────────────────────────────
  [●] Running: 0/5 Queue  |  [✓] 0 SUCCESS  |  [×] 0 FAILED  |  0.0s
 ──────────────────────────────────────────────────────────────────────

  [01] Open x.ai signup
    ✓ page loaded

  [02] Sign up with email
    ✓ email form

  [03] Create temp email
    → user@domain.com
    ✓ email submitted

  [04] Wait for OTP
    ⠹ waiting OTP 3s
    ✓ OTP: X43A4D

  [05] Submit OTP
    ✓ verified

  [06] Fill name & password
    → John Doe
    ✓ form filled

  [07] Solve turnstile & submit
    ✓ turnstile solved
    submitting ■■■■■■□□
    ✓ submitted

  [08] Redirect → grok.com
    ✓ → https://grok.com/

  [09] Save credentials
    ✓ saved → sso.txt
 ──────────────────────────────────────────────────────────────────────
  1   user@domain.com  [09] done  SUCCESS 17.5s
 ──────────────────────────────────────────────────────────────────────

 ┌── [ SYSTEM LOGS ] ───────────────────────────────────────────
 │ DONE   [001] user@domain.com → grok.com (17.5s)
 └────────────────────────────────────────────────────────────────────

 [ Diagnostics ]───────────────────────────────────────────────
  Health 100.0%  |  Speed 3.0/m  |  Errors 0
  TOTAL [■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■] 5/5 100%
```

---

## 🚨 Troubleshooting

<details>
<summary><b>🔐 "OTP gak masuk 120s"</b></summary>

- Cek `MAILLDEZ_URL` + `MAILLDEZ_DOMAINS` di `.env`
- Test API: `curl https://your-mail-api.example/api/session`
- Pastikan domain di `.env` resolve di DNS

</details>

<details>
<summary><b>🛡️ "Turnstile gak solved 40s"</b></summary>

- Pastikan folder `turnstilePatch/` ada di direktori yang sama
- Chrome extension butuh `--load-extension` (auto di script)
- Restart browser context kalau extension gak load

</details>

<details>
<summary><b>🔑 "SSO expired, need login"</b></summary>

- Cookies SSO expired (x.ai session timeout)
- Re-register akun baru atau login manual untuk refresh SSO
- SSO cookies lifespan ±6 jam

</details>

<details>
<summary><b>🔒 "Password too weak"</b></summary>

- x.ai reject password < 16 karakter
- Update `PASSWORD` di `.env`
- Format: huruf besar + kecil + angka + simbol (min 16 char)

</details>

<details>
<summary><b>☁️ "Cloudflare Attention Required"</b></summary>

- IP server di-block Cloudflare x.ai
- Jangan pakai proxy (WARP/SG exit di-block)
- Headless deteksi bot — wajib pakai Xvfb (`xvfb-run -a`)

</details>

<details>
<summary><b>🔗 "9Router login failed"</b></summary>

- Cek `ROUTER9_URL` + `ROUTER9_PASS` di `.env`
- Test login: `curl -X POST $ROUTER9_URL/api/auth/login -d '{"password":"..."}'`

</details>

---

## 📝 Notes

| Item | Detail |
|------|--------|
| ⏱️ Speed | ±17-20 detik per akun (tanpa proxy) |
| 🎲 Domain | Rotasi round-robin biar gak kena rate-limit |
| 📝 sso.txt | Append mode — gak overwrite, bisa run berkali-kali |
| 🌐 Chrome | `channel='chrome'` (bukan chromium) — butuh Google Chrome stable |
| 🖥️ Display | Xvfb wajib — headless deteksi bot |
| 🚫 Proxy | Jangan pakai — WARP/SG exit di-block Cloudflare |

---

<div align="center">

**⚠️ Disclaimer: Untuk educational purposes only.**

</div>

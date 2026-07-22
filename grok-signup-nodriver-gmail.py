#!/usr/bin/env python3
"""grok-signup-nodriver-gmail.py — nodriver + Gmail IMAP version.

Uses nodriver's built-in verify_cf() for Turnstile bypass (more reliable than extension).
Combines:
- nodriver browser automation with verify_cf()
- Gmail IMAP OTP polling
- ProxyPool with failure tracking
- Human-like typing simulation
- Same capabilities: infinite loop, batch, auto-add, retries
"""
import asyncio
import json
import os
import random
import re
import string
import sys
import time
import imaplib
from email import message_from_bytes
from pathlib import Path

import nodriver as uc
import requests

# Import Turnstile solver
from turnstile_solver import solve_turnstile

# ── Config ────────────────────────────────────────────────────
_env = {}
_envfile = Path(__file__).parent / '.env'
if _envfile.exists():
    for line in _envfile.read_text().splitlines():
        if '=' in line and not line.startswith('#'):
            k, v = line.split('=', 1)
            _env[k.strip()] = v.strip()

def _env_or(key, default): return os.environ.get(key, _env.get(key, default))

PASSWORD = _env_or('PASSWORD', 'change-me')
GMAIL_USER = _env_or('GMAIL_USER', '')
GMAIL_APP_PASSWORD = _env_or('GMAIL_APP_PASSWORD', '')
GMAIL_DOMAINS = _env_or('GMAIL_DOMAINS', 'example.com').split(',')
ROUTER9 = _env_or('ROUTER9_URL', 'https://your-9router.example')
ROUTER9_PASS = _env_or('ROUTER9_PASS', 'change-me')

# Proxy config
PROXY_MAX_FAILURES = max(1, int(_env_or('PROXY_MAX_FAILURES', '3')))  # Proxy blacklist threshold

# ── Proxy Pool Manager ───────────────────────────────────────
class ProxyPool:
    """Proxy pool with failure tracking and blacklisting.

    Proxies failing PROXY_MAX_FAILURES times are blacklisted. When all proxies dead, returns None (fallback to direct).
    """
    def __init__(self, proxies: list, max_failures: int = 3):
        self._proxies = {}  # proxy_url -> failure_count
        self._max_failures = max_failures

        for proxy in proxies:
            proxy = proxy.strip()
            if not proxy:
                continue
            # Extract IP:port from format like "129.222.204.27:10000 NG-N-S +"
            match = re.match(r'^([\d\.]+:\d+)', proxy)
            if match:
                clean_proxy = match.group(1)
                self._proxies[clean_proxy] = 0

        # Silent init - logging done by caller

    def get_random_proxy(self):
        """Get random working proxy, or None if all blacklisted."""
        available = [p for p, fails in self._proxies.items() if fails < self._max_failures]

        if not available:
            return None

        return random.choice(available)

    def report_failure(self, proxy):
        """Increment failure count. Blacklist at max_failures."""
        if not proxy or proxy not in self._proxies:
            return
        self._proxies[proxy] += 1

    def report_success(self, proxy):
        """Report success (keeps failure history)."""
        pass  # No-op, keep failure count

    def get_stats(self):
        """Get pool stats."""
        total = len(self._proxies)
        blacklisted = sum(1 for fails in self._proxies.values() if fails >= self._max_failures)
        available = total - blacklisted

        return {
            'total': total,
            'available': available,
            'blacklisted': blacklisted,
            'max_failures': self._max_failures,
        }

# Load proxy pool
PROXY_LIST_RAW = _env_or('PROXIES', '')
PROXY_POOL = None
if PROXY_LIST_RAW:
    proxy_lines = [line.strip() for line in PROXY_LIST_RAW.split(',') if line.strip()]
    if proxy_lines:
        PROXY_POOL = ProxyPool(proxy_lines, max_failures=PROXY_MAX_FAILURES)
    else:
        log_no("PROXIES env empty - running without proxy")

SIGNUP = 'https://accounts.x.ai/sign-up?redirect=grok-com'
OUT = Path('sso.txt')

MAX_ACCOUNTS = int(_env_or('MAX_ACCOUNTS', '1'))    # <= 0 = infinite
BATCH_SIZE = max(1, int(_env_or('BATCH_SIZE', '1')))
PAUSE_SECONDS = int(_env_or('PAUSE_SECONDS', '10'))
DELAY_SECONDS = int(_env_or('DELAY_SECONDS', '5'))
MAX_ACCOUNT_RETRIES = max(1, int(_env_or('MAX_ACCOUNT_RETRIES', '3')))
AUTO_ADD = os.environ.get('AUTO_ADD', 'false').lower() in ('1','true','yes')

_used_addrs = set()
GRN, RED, YEL, CYN, RST, BOLD = '\033[32m', '\033[31m', '\033[33m', '\033[36m', '\033[0m', '\033[1m'

def log_ok(msg): print(f"  {GRN}✓{RST} {msg}", flush=True)
def log_no(msg): print(f"  {RED}✗{RST} {msg}", flush=True)
def log_wait(msg): print(f"  {YEL}→{RST} {msg}", flush=True)

class TurnstileRetry(Exception):
    """Raised when Turnstile fails but account data can be reused for retry."""
    def __init__(self, mail, code):
        super().__init__('Turnstile retry needed')
        self.mail = mail
        self.code = code

def unique_addr():
    for _ in range(20):
        local = (
            ''.join(random.choices(string.ascii_lowercase, k=5)) + '.'
            + ''.join(random.choices(string.ascii_lowercase, k=5)) + '.'
            + ''.join(random.choices('0123456789abcdef', k=4))
        )
        dom = random.choice(GMAIL_DOMAINS)
        addr = f'{local}@{dom}'
        if addr not in _used_addrs:
            _used_addrs.add(addr)
            return addr
    raise RuntimeError('could not generate unique email')

# unlock_turnstile() removed — nodriver verify_cf() handles Turnstile
# But keep is_turnstile_present() for detection/retry logic
async def is_turnstile_present(page) -> bool:
    """Check if Turnstile CAPTCHA is present on page."""
    try:
        return await page.evaluate('''(() => {
            // Check for Turnstile input fields
            if (document.querySelector('input[name="cf_challenge_response"]')) return true;
            if (document.querySelector('input[name="cf-turnstile-response"]')) return true;

            // Check for Cloudflare challenge iframes
            const iframes = document.querySelectorAll("iframe");
            for (const f of iframes) {
                if (f.src && f.src.includes("challenges.cloudflare.com")) return true;
            }

            // Check body text for challenge prompts
            const body = document.body.innerText || "";
            if (body.includes("Verify you are human")) return true;
            if (body.includes("Let us know you are human")) return true;

            return false;
        })()''')
    except:
        return False

# ── Gmail IMAP ────────────────────────────────────────────────
class GmailIMAP:
    def __init__(self):
        self.mail = None
        self.addr = None
        self._seen_ids = set()

    def create(self):
        self.addr = unique_addr()
        self.mail = imaplib.IMAP4_SSL('imap.gmail.com')
        self.mail.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        self.mail.select('inbox')
        return self.addr

    @staticmethod
    def _extract_code(text):
        patterns = [
            r'code[:\s]+([A-Z0-9]{3}-[A-Z0-9]{3})',  # "code: ZS8-UTP" or "code U5R-4UC"
            r'code[:\s]+([A-Z0-9]{6})',              # "code: ZS8UTP" or "code ZS8UTP"
            r'\b([A-Z0-9]{3}-[A-Z0-9]{3})\b',        # word boundary "U5R-4UC"
            r'\b([A-Z0-9]{6})\b',                    # word boundary "U5R4UC"
        ]
        for pat in patterns:
            m = re.search(pat, text, re.I)
            if m:
                code = m.group(1).replace('-', '')
                if len(code) == 6 and code.isalnum() and code.isupper():
                    return code
        return None

    def _body_text(self, msg):
        parts = []
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == 'text/plain':
                    payload = part.get_payload(decode=True)
                    if payload:
                        parts.append(payload.decode('utf-8', errors='ignore'))
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                parts.append(payload.decode('utf-8', errors='ignore'))
        return '\n'.join(parts)

    def peek_code(self):
        try:
            self.mail.noop()
            _, search_data = self.mail.search(None, f'TO "{self.addr}"')
            msg_ids = search_data[0].split()

            # Debug: log email count
            if msg_ids:
                log_wait(f"found {len(msg_ids)} emails for {self.addr}")

            for mid in msg_ids:
                if mid in self._seen_ids:
                    continue
                _, fetched = self.mail.fetch(mid, '(RFC822)')
                raw = fetched[0][1]
                msg = message_from_bytes(raw)

                # Debug: log email details (FULL subject, not truncated)
                subj = msg.get('Subject', '')
                from_addr = msg.get('From', '')
                log_wait(f"Email: From={from_addr[:50]}, Subject={subj}")

                # Try extract from SUBJECT FIRST (more reliable than HTML body)
                code = self._extract_code(subj)
                if code:
                    log_ok(f"✓ Extracted OTP: {code} from SUBJECT")
                    self._seen_ids.add(mid)
                    # Delete the email after extracting OTP
                    self.mail.store(mid, '+FLAGS', '\\Deleted')
                    self.mail.expunge()
                    log_ok(f"deleted OTP email")
                    return code

                # Fallback: try body
                text = self._body_text(msg)
                if text:
                    log_wait(f"Body snippet: {text[:100]}")
                    code = self._extract_code(text)
                    if code:
                        log_ok(f"✓ Extracted OTP: {code} from BODY")
                        self._seen_ids.add(mid)
                        # Delete the email after extracting OTP
                        self.mail.store(mid, '+FLAGS', '\\Deleted')
                        self.mail.expunge()
                        log_ok(f"deleted OTP email")
                        return code

                log_wait(f"No OTP match in this email")
                self._seen_ids.add(mid)
        except Exception as e:
            log_no(f"Gmail peek error: {e}")
        return None

    def logout(self):
        try:
            self.mail.close()
            self.mail.logout()
        except Exception:
            pass

def wait_for_otp(mail: GmailIMAP, timeout: int = 120):
    """Poll Gmail IMAP for OTP code."""
    t = time.time()
    while time.time() - t < timeout:
        code = mail.peek_code()
        if code:
            return code
        time.sleep(0.5)
    return None

# ── 9Router helper ─────────────────────────────────────────────
class Router9:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update({'Accept':'application/json','Content-Type':'application/json'})
        self.auth_token = None

    def login(self):
        r = self.s.post(f'{ROUTER9}/api/auth/login', json={'password':ROUTER9_PASS}, timeout=15)
        # Extract auth_token from Set-Cookie header
        if 'Set-Cookie' in r.headers:
            cookies = r.headers['Set-Cookie']
            match = re.search(r'auth_token=([^;]+)', cookies)
            if match:
                self.auth_token = match.group(1)
                self.s.cookies.set('auth_token', self.auth_token)
        return r.json().get('success', False)

    def device_code(self):
        r = self.s.get(f'{ROUTER9}/api/oauth/grok-cli/device-code', timeout=60)
        return r.json()

    def poll(self, device_code, code_verifier):
        url = f'{ROUTER9}/api/oauth/grok-cli/poll'
        payload = {'deviceCode': device_code, 'codeVerifier': code_verifier}

        # Debug logging
        print(f"→ Router9 poll request:")
        print(f"  URL: {url}")
        print(f"  deviceCode: {device_code[:30]}...")
        print(f"  codeVerifier: {code_verifier[:30]}...")
        print(f"  timeout: 60s")

        try:
            r = self.s.post(url, json=payload, timeout=60)
            print(f"→ Router9 poll response:")
            print(f"  status: {r.status_code}")
            print(f"  headers: {dict(r.headers)}")
            print(f"  body: {r.text[:500]}")
            return r.json()
        except Exception as e:
            print(f"✗ Router9 poll network error: {type(e).__name__}: {e}")
            raise

    def list_providers(self):
        r = self.s.get(f'{ROUTER9}/api/providers', timeout=15)
        conns = r.json().get('connections', [])
        return [c for c in conns if c.get('provider') == 'grok-cli']

# ── Main signup flow ──────────────────────────────────────────
async def signup_one(email_code_pair=None):
    """Register one Grok account. Returns account dict or raises exception."""
    # Step 1: Get device code from 9router
    r9 = Router9()
    if not r9.login():
        raise RuntimeError("9router login failed")

    device_data = r9.device_code()
    device_code = device_data.get('device_code')
    code_verifier = device_data.get('codeVerifier')
    user_code = device_data.get('user_code')
    verification_uri_complete = device_data.get('verification_uri_complete')

    if not device_code or not code_verifier or not user_code:
        raise RuntimeError(f"invalid device_code response: {device_data}")

    log_ok(f"device code: {user_code}")

    # Build signup URL with OAuth redirect
    import urllib.parse
    return_to = urllib.parse.quote(f'/oauth2/device?user_code={user_code}')
    signup_url = f'https://accounts.x.ai/sign-up?redirect=oauth2-provider&return_to={return_to}'
    log_ok(f"signup URL: {signup_url}")

    # Pick proxy from pool
    proxy_server = None
    if PROXY_POOL:
        proxy_server = PROXY_POOL.get_random_proxy()
        if proxy_server:
            log_ok(f"using proxy: {proxy_server} (failures: {PROXY_POOL._proxies.get(proxy_server, 0)}/{PROXY_POOL._max_failures})")
        else:
            log_no("all proxies blacklisted - using direct connection")

    signup_success = False
    try:
        log_wait("launching nodriver browser...")
        log_wait(f"  Proxy: {proxy_server or 'none'}")

        # Match bulk-cf Chrome args for better Turnstile bypass in Docker
        browser = await uc.start(
            headless=False,
            browser_args=[
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-features=IsolateOrigins,site-per-process',
                '--disable-blink-features=AutomationControlled',
            ]
        )
        page = await browser.get(signup_url)
        await asyncio.sleep(4)

        # Diagnostic: log actual URL and title after load
        actual_url = page.url
        page_title = await page.evaluate("document.title")
        log_wait(f"loaded: {actual_url}")
        log_wait(f"title: {page_title}")

        # Check for error pages
        page_text = (await page.evaluate("document.body.innerText || ''"))[:200]
        if any(err in page_text.lower() for err in ['access denied', 'blocked', 'captcha', 'rate limit', '403', '429']):
            log_no(f"possible block: {page_text[:100]}")

        log_ok("page loaded")

        # Cookie banner
        try:
            btn = await page.find('Accept All Cookies', timeout=3)
            if btn:
                await btn.click()
                await asyncio.sleep(0.5)
        except:
            pass

        try:
            el = await page.find('Sign up with email', timeout=15)
            await el.click()
            await page.select('input[type=email]', timeout=8)
            await asyncio.sleep(2)
            log_ok("email form")
        except Exception as e:
            browser.stop()
            raise RuntimeError(f"email form: {e}")

        # Reuse existing mail+code if retrying
        if email_code_pair:
            mail = email_code_pair[0]
            addr = mail.addr
            code = email_code_pair[1]
            log_wait(f"retrying {addr}")
        else:
            mail = GmailIMAP()
            addr = mail.create()
            code = None
        log_wait(addr)

        email_input = await page.select('input[type=email]')
        for char in addr:
            await email_input.send_keys(char)
            await asyncio.sleep(random.uniform(0.05, 0.15))

        # Click Sign up button immediately (no Enter key delay)
        try:
            btn = await page.find('Sign up', timeout=3)
            if btn:
                await btn.click()
        except:
            await email_input.send_keys('\n')

        # Wait for OTP input
        await page.select('input[name=code]', timeout=20)
        log_ok("email submitted")

        if not code:
            code = wait_for_otp(mail, timeout=120)
            if not code:
                mail.logout()
                browser.stop()
                raise RuntimeError("OTP timeout 120s")
        log_ok(f"OTP: {code}")

        code_input = await page.select('input[name=code]')
        for char in code:
            await code_input.send_keys(char)
            await asyncio.sleep(random.uniform(0.1, 0.2))
        await asyncio.sleep(0.3)
        log_wait("submitting OTP...")
        await code_input.send_keys('\n')
        await page.select('input[name=givenName]', timeout=20)
        log_ok("OTP verified")

        local = addr.split('@')[0]
        parts = re.split(r'[._\-]', local)
        given = parts[0].capitalize()
        family = (parts[1] if len(parts) > 1 else 'Xyz').capitalize()

        given_input = await page.select('input[name=givenName]')
        for char in given:
            await given_input.send_keys(char)
            await asyncio.sleep(random.uniform(0.08, 0.18))

        family_input = await page.select('input[name=familyName]')
        for char in family:
            await family_input.send_keys(char)
            await asyncio.sleep(random.uniform(0.08, 0.18))

        password_input = await page.select('input[name=password]')
        for char in PASSWORD:
            await password_input.send_keys(char)
            await asyncio.sleep(random.uniform(0.06, 0.12))
        log_ok("form filled")

        # Hybrid Turnstile bypass: call solver every 3 clicks + poll button
        log_wait("hybrid Turnstile bypass (solver + polling)...")
        poll_start = time.time()
        poll_timeout = 40  # 40s max
        oauth_reached = False
        click_count = 0
        solver_called = False

        while time.time() - poll_start < poll_timeout:
            try:
                # Call solve_turnstile every 3 clicks (at 0, 3, 6...)
                if click_count % 3 == 0 and not solver_called:
                    log_wait(f"calling Turnstile solver (click #{click_count})...")
                    token = await solve_turnstile(page, timeout=8)
                    if token:
                        log_ok(f"solver returned token: {token[:20]}...")
                    else:
                        log_wait("solver timeout, continuing polling...")
                    solver_called = True
                elif click_count % 3 != 0:
                    solver_called = False  # Reset for next cycle

                # Try find and click submit button
                submit_btn = await page.find('Complete sign up', timeout=2)
                if submit_btn:
                    await submit_btn.click()
                    click_count += 1
                    log_wait(f"clicked Complete sign up #{click_count} (elapsed: {int(time.time() - poll_start)}s)")
                    await asyncio.sleep(2)  # Wait for navigation

                    # Check if we reached OAuth page
                    current_url = await page.evaluate("window.location.href")
                    if 'oauth2/device?user_code=' in current_url:
                        oauth_reached = True
                        log_ok(f"navigation succeeded after {click_count} clicks, {int(time.time() - poll_start)}s")
                        break
                else:
                    log_wait("Complete sign up button not found, retrying...")
                    await asyncio.sleep(2)
            except Exception as e:
                # Button click failed (likely Turnstile blocking), retry
                log_wait(f"submit blocked: {e}, retrying... ({int(time.time() - poll_start)}s)")
                await asyncio.sleep(2)

        if not oauth_reached:
            mail.logout()
            browser.stop()
            raise RuntimeError(f"Turnstile bypass failed after {click_count} clicks, {int(time.time() - poll_start)}s")

        # Wait for navigation to OAuth page after submit
        log_wait("waiting for redirect to OAuth page...")
        oauth_reached = False
        for i in range(20):
            # Use evaluate to get current URL (more reliable than page.url property)
            current_url = await page.evaluate("window.location.href")
            if 'oauth2/device?user_code=' in current_url:
                oauth_reached = True
                log_ok(f"redirected to OAuth page: {current_url}")
                break
            if i % 5 == 0 and i > 0:
                log_wait(f"still waiting for OAuth redirect... (current: {current_url})")
            await asyncio.sleep(1)

        # If stuck on signup page with return_to param, manually navigate
        if not oauth_reached:
            current_url = await page.evaluate("window.location.href")
            if 'return_to=' in current_url and 'oauth2/device' in current_url:
                # Extract the return_to URL and navigate to it
                import urllib.parse
                parsed = urllib.parse.urlparse(current_url)
                params = urllib.parse.parse_qs(parsed.query)
                return_to = params.get('return_to', [''])[0]

                if return_to:
                    # Build full OAuth URL
                    oauth_url = f"https://accounts.x.ai{return_to}"
                    log_wait(f"auto-redirect failed, navigating manually to: {oauth_url}")
                    await page.get(oauth_url)
                    await asyncio.sleep(3)

                    # Check if we reached OAuth page now
                    current_url = await page.evaluate("window.location.href")
                    if 'oauth2/device?user_code=' in current_url:
                        oauth_reached = True
                        log_ok(f"manual navigation succeeded: {current_url}")

        if not oauth_reached:
            current_url = await page.evaluate("window.location.href")
            page_text = await page.evaluate("document.body.innerText || ''")
            log_no(f"OAuth page not reached after 20s + manual navigation")
            log_no(f"Current URL: {current_url}")
            log_no(f"Page text: {page_text[:300]}")
            mail.logout()
            browser.stop()
            raise RuntimeError(f"did not reach OAuth page, stuck at: {current_url}")

        # Wait for OAuth page to be ready
        await asyncio.sleep(2)

        # Check current URL
        current_url = await page.evaluate("window.location.href")
        log_wait(f"OAuth page: {current_url}")

        # Click Continue button
        log_wait("looking for Continue button...")
        try:
            btn = await page.find('Continue', timeout=5)
            if btn:
                await btn.click()
                await asyncio.sleep(2)
                current_url = await page.evaluate("window.location.href")
                log_ok(f"Continue clicked → {current_url}")
            else:
                log_wait("Continue button not found (may auto-continue)")
        except Exception as e:
            log_wait(f"Continue button error: {e}")

        # Wait for consent page
        await asyncio.sleep(2)

        # Click Allow button with action=allow
        log_wait("looking for Allow button...")
        try:
            allow_found = await page.evaluate("""
                (function() {
                    const btns = Array.from(document.querySelectorAll('button[type="submit"]'));
                    return btns.some(b => b.textContent.trim() === 'Allow');
                })();
            """)

            if allow_found:
                log_wait("Allow button found, clicking...")

                # Set action=allow and click
                await page.evaluate("""
                    (function() {
                        const actionInput = document.querySelector('input[name="action"]');
                        if (actionInput) {
                            actionInput.value = 'allow';
                        }

                        const btns = Array.from(document.querySelectorAll('button[type="submit"]'));
                        const allowBtn = btns.find(b => b.textContent.trim() === 'Allow');
                        if (allowBtn) {
                            allowBtn.click();
                        }
                    })();
                """)

                log_ok("Allow button clicked")

                # Wait for redirect
                await asyncio.sleep(3)
                current_url = await page.evaluate("window.location.href")
                log_ok(f"after Allow: {current_url}")

                # If /approve error, retry once
                if '/approve' in current_url:
                    log_wait("/approve error, retrying...")
                    await page.evaluate("window.history.back()")
                    await asyncio.sleep(2)

                    await page.evaluate("""
                        (function() {
                            const actionInput = document.querySelector('input[name="action"]');
                            if (actionInput) {
                                actionInput.value = 'allow';
                            }
                            const btns = Array.from(document.querySelectorAll('button[type="submit"]'));
                            const allowBtn = btns.find(b => b.textContent.trim() === 'Allow');
                            if (allowBtn) {
                                allowBtn.click();
                            }
                        })();
                    """)

                    await asyncio.sleep(3)
                    current_url = await page.evaluate("window.location.href")
                    log_ok(f"after retry: {current_url}")
            else:
                log_wait("Allow button not found")
                page_text = await page.evaluate("document.body.innerText || ''")
                log_wait(f"Page text: {page_text[:200]}")
        except Exception as e:
            log_wait(f"Allow error: {e}")

        # Close browser
        final_url = await page.evaluate("window.location.href")
        log_ok(f"final URL: {final_url}")

        mail.logout()
        browser.stop()

        # Poll 9router with retry mechanism
        log_wait(f"polling 9router (device_code: {device_code[:20]}..., verifier: {code_verifier[:20]}...)")
        poll_success = False
        max_poll_attempts = 20

        for attempt in range(1, max_poll_attempts + 1):
            try:
                res = r9.poll(device_code, code_verifier)
                log_wait(f"poll attempt {attempt}: {res}")

                if res.get('success'):
                    log_ok(f"✓ 9router import success (attempt {attempt}/{max_poll_attempts})")
                    poll_success = True
                    break
                if not res.get('pending'):
                    log_no(f"poll error (attempt {attempt}): {res.get('error', 'unknown')}, retrying...")
                    time.sleep(5)
                    continue
                if attempt % 3 == 0:
                    log_wait(f"still polling... (attempt {attempt}/{max_poll_attempts}, status: pending)")
                time.sleep(5)
            except Exception as poll_err:
                log_no(f"poll exception (attempt {attempt}): {poll_err}, retrying...")
                time.sleep(5)
                continue

        if not poll_success:
            raise RuntimeError(f"9router poll failed after {max_poll_attempts} attempts - account created but not imported!")

        # Collect cookies (browser already closed, use empty list)
        sso_cookies = []

        # Check if we have JWT token (skip - browser closed)
        jwt_found = False

        data = {
            'email': addr,
            'password': PASSWORD,
            'code': code,
            'sso_cookies': sso_cookies,
            'final_url': '',
            'timestamp': int(time.time()),
        }

        # Save to sso.txt (JSON lines)
        OUT.parent.mkdir(parents=True, exist_ok=True)
        with open(OUT, 'a') as f:
            f.write(json.dumps(data) + '\n')
        log_ok(f"saved → {OUT}")

        # Save to ~/.grok/auth.json (Grok CLI format)
        grok_dir = Path.home() / '.grok'
        grok_auth = grok_dir / 'auth.json'
        grok_dir.mkdir(parents=True, exist_ok=True)

        # Extract JWT token from sso cookie (.x.ai domain)
        jwt_token = None
        for c in sso_cookies:
            if c['name'] == 'sso' and '.x.ai' in c.get('domain', ''):
                jwt_token = c['value']
                break

        # Load existing auth or create new
        if grok_auth.exists():
            try:
                grok_data = json.loads(grok_auth.read_text())
            except:
                grok_data = {'accounts': []}
        else:
            grok_data = {'accounts': []}

        # Add account (avoid duplicates)
        existing_emails = {acc.get('email') for acc in grok_data.get('accounts', [])}
        if addr not in existing_emails:
            grok_data['accounts'].append({
                'email': addr,
                'token': jwt_token,
            })
            grok_auth.write_text(json.dumps(grok_data, indent=2))
            log_ok(f"saved → {grok_auth}")

        # Report proxy success
        if PROXY_POOL and proxy_server:
            PROXY_POOL.report_success(proxy_server)
            log_ok(f"proxy success: {proxy_server}")

        return data

    except Exception as e:
        # Report proxy failure
        if PROXY_POOL and proxy_server:
            PROXY_POOL.report_failure(proxy_server)
            failures = PROXY_POOL._proxies.get(proxy_server, 0)
            log_no(f"proxy failed: {proxy_server} ({failures}/3)")
            if failures >= 3:
                log_no(f"proxy BLACKLISTED: {proxy_server}")
        raise

# ── Infinite runner ───────────────────────────────────────────
def run_accounts():
    """Run infinite or bounded account creation loop."""
    auto_add = AUTO_ADD or '--auto-add' in sys.argv
    max_accounts = MAX_ACCOUNTS
    total = ok_n = fail_n = 0
    total_imported = 0  # Track successful 9router imports
    successful_accounts = []

    print(f"\n{CYN}{'='*74}{RST}")
    print(f"{CYN}║{RST} {BOLD}GROK SIGNUP + 9ROUTER AUTO-IMPORT (nodriver){RST}")
    print(f"{CYN}{'='*74}{RST}")
    print(f"{CYN}║{RST} Mode: {'INFINITE' if max_accounts <= 0 else f'{max_accounts} accounts'}")
    print(f"{CYN}║{RST} Batch Size: {BATCH_SIZE}")
    print(f"{CYN}║{RST} Auto-Import: {'YES' if auto_add else 'NO'}")

    # Proxy pool stats
    if PROXY_POOL:
        stats = PROXY_POOL.get_stats()
        print(f"{CYN}║{RST} Proxy Pool: {stats['total']} total, {stats['available']} available (blacklist at {stats['max_failures']} failures)")
    else:
        print(f"{YEL}║{RST} Proxy Pool: disabled (PROXIES env not set)")

    print(f"{CYN}║{RST} Account Retries: {MAX_ACCOUNT_RETRIES}")
    print(f"{CYN}║{RST} Delay Between Accounts: {DELAY_SECONDS}s")
    print(f"{CYN}║{RST} Pause Between Batches: {PAUSE_SECONDS}s")
    print(f"{CYN}{'='*74}{RST}\n")

    while max_accounts <= 0 or total < max_accounts:
        batch_target = min(BATCH_SIZE, (max_accounts - total) if max_accounts > 0 else BATCH_SIZE)
        batch_imported = 0  # Track imports in this batch

        print(f"\n{CYN}┌─ BATCH #{(total // BATCH_SIZE) + 1} ─{'─'*58}{RST}")

        for i in range(batch_target):
            total += 1
            t0 = time.time()
            email_code_pair = None
            last_ex = None

            print(f"{CYN}│{RST} [{total}] Starting account creation...")

            for attempt in range(1, MAX_ACCOUNT_RETRIES + 1):
                try:
                    acc = asyncio.run(signup_one(email_code_pair))
                    ok_n += 1
                    elapsed = time.time() - t0
                    print(f"{GRN}│ ✓{RST} [{total}] {acc['email']} → imported in {elapsed:.1f}s")
                    total_imported += 1
                    batch_imported += 1

                    if auto_add:
                        successful_accounts.append(acc)
                    break
                except TurnstileRetry as e:
                    email_code_pair = (e.mail, e.code)
                    last_ex = e
                    log_no(f"[{total}] Turnstile retry {attempt}/{MAX_ACCOUNT_RETRIES}")
                except Exception as e:
                    last_ex = e
                    fail_n += 1
                    print(f"{RED}│ ✗{RST} [{total}] Failed: {e}")
                    break
            else:
                # Retries exhausted
                fail_n += 1
                print(f"{RED}│ ✗{RST} [{total}] Failed after {MAX_ACCOUNT_RETRIES} retries")

            if i < batch_target - 1:
                print(f"{CYN}│{RST} Delaying {DELAY_SECONDS}s before next account...")
                time.sleep(DELAY_SECONDS)

        # Batch summary
        print(f"{CYN}└─{'─'*70}{RST}")
        print(f"\n{GRN}■{RST} Batch Summary:")
        print(f"  ├─ Imported: {batch_imported}/{batch_target}")
        print(f"  ├─ Failed: {batch_target - batch_imported}")
        print(f"  └─ Total Imported (all batches): {GRN}{total_imported}{RST}")

        # Proxy pool stats
        if PROXY_POOL:
            stats = PROXY_POOL.get_stats()
            print(f"\n{CYN}■{RST} Proxy Pool Stats:")
            print(f"  ├─ Available: {GRN}{stats['available']}{RST}/{stats['total']}")
            print(f"  └─ Blacklisted: {RED}{stats['blacklisted']}{RST}")

        print(f"\n{CYN}■{RST} Overall Stats:")
        print(f"  ├─ Total Attempts: {total}")
        print(f"  ├─ Successful: {GRN}{ok_n}{RST}")
        print(f"  ├─ Failed: {RED}{fail_n}{RST}")
        print(f"  └─ Success Rate: {int(ok_n/total*100) if total else 0}%")

        if max_accounts > 0 and total >= max_accounts:
            break

        if max_accounts <= 0 or total < max_accounts:
            print(f"\n{YEL}→{RST} Sleeping {PAUSE_SECONDS}s before next batch...\n")
            time.sleep(PAUSE_SECONDS)

    print(f"\n{CYN}{'='*74}{RST}")
    print(f"{CYN}║{RST} {BOLD}FINAL REPORT{RST}")
    print(f"{CYN}{'='*74}{RST}")
    print(f"{GRN}║{RST} Total Imported to 9router: {GRN}{BOLD}{total_imported}{RST}")
    print(f"{GRN}║{RST} Success: {ok_n}  |  {RED}Failed: {fail_n}{RST}  |  Total: {total}")
    print(f"{CYN}{'='*74}{RST}\n")

# ── CLI ───────────────────────────────────────────────────────
if __name__ == '__main__':
    try:
        run_accounts()
    except KeyboardInterrupt:
        print(f"\n{YEL}stopped by user{RST}")

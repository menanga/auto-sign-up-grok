#!/usr/bin/env python3
"""grok-signup-playwright-gmail.py — Playwright + Gmail IMAP version.

Combines:
- Playwright browser automation (from grok-signup.py)
- Gmail IMAP OTP polling (from grok-signup-nodriver.py)
- turnstilePatch extension for Turnstile bypass
- Same capabilities: infinite loop, batch, auto-add, retries
"""
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

from playwright.sync_api import sync_playwright
import curl_cffi.requests as creq

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

# ── Proxy Pool Manager ───────────────────────────────────────
class ProxyPool:
    """Proxy pool with failure tracking and blacklisting.

    Proxies failing 3 times are blacklisted. When all proxies dead, returns None (fallback to direct).
    """
    def __init__(self, proxies: list):
        self._proxies = {}  # proxy_url -> failure_count

        for proxy in proxies:
            proxy = proxy.strip()
            if not proxy:
                continue
            # Extract IP:port from format like "129.222.204.27:10000 NG-N-S +"
            match = re.match(r'^([\d\.]+:\d+)', proxy)
            if match:
                clean_proxy = match.group(1)
                self._proxies[clean_proxy] = 0

        log_ok(f"proxy pool: {len(self._proxies)} loaded")

    def get_random_proxy(self):
        """Get random working proxy, or None if all blacklisted."""
        available = [p for p, fails in self._proxies.items() if fails < 3]

        if not available:
            log_no("all proxies blacklisted (3+ failures) - fallback to direct")
            return None

        proxy = random.choice(available)
        log_wait(f"selected proxy: {proxy} (failures: {self._proxies[proxy]}/3)")
        return proxy

    def report_failure(self, proxy):
        """Increment failure count. Blacklist at 3."""
        if not proxy or proxy not in self._proxies:
            return

        self._proxies[proxy] += 1
        log_no(f"proxy failed: {proxy} ({self._proxies[proxy]}/3 failures)")

        if self._proxies[proxy] >= 3:
            log_no(f"proxy BLACKLISTED: {proxy}")

    def report_success(self, proxy):
        """Report success (keeps failure history)."""
        if not proxy or proxy not in self._proxies:
            return

        log_ok(f"proxy success: {proxy} (failures: {self._proxies[proxy]})")

    def get_stats(self):
        """Get pool stats."""
        total = len(self._proxies)
        blacklisted = sum(1 for fails in self._proxies.values() if fails >= 3)
        available = total - blacklisted

        return {
            'total': total,
            'available': available,
            'blacklisted': blacklisted,
        }

# Load proxy pool
PROXY_LIST_RAW = _env_or('PROXIES', '')
PROXY_POOL = None
if PROXY_LIST_RAW:
    proxy_lines = [line.strip() for line in PROXY_LIST_RAW.split(',') if line.strip()]
    if proxy_lines:
        PROXY_POOL = ProxyPool(proxy_lines)
    else:
        log_no("PROXIES env empty - running without proxy")

# Auto-detect Chrome binary
def _detect_chrome():
    candidates = [
        '/usr/bin/google-chrome',
        '/usr/bin/google-chrome-stable',
        '/usr/bin/chromium',
        '/usr/bin/chromium-browser',
        None,  # Let Playwright use bundled Chrome
    ]
    env_chrome = _env_or('CHROME_BIN', '')
    if env_chrome:
        return env_chrome

    import shutil
    for path in candidates:
        if path is None:
            return None
        if shutil.which(path) or Path(path).exists():
            return path
    return None

CHROME_BIN = _detect_chrome()
TS_DIR = Path('turnstilePatch').resolve()
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

def unlock_turnstile():
    """Return path to turnstilePatch directory."""
    if not (TS_DIR / 'script.js').exists() or not (TS_DIR / 'manifest.json').exists():
        raise RuntimeError(f"missing turnstilePatch/script.js or manifest.json in {TS_DIR}")
    return str(TS_DIR)

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
        self.s = creq.Session()
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
        r = self.s.post(f'{ROUTER9}/api/oauth/grok-cli/poll',
                        json={'deviceCode': device_code, 'codeVerifier': code_verifier}, timeout=60)
        return r.json()

    def list_providers(self):
        r = self.s.get(f'{ROUTER9}/api/providers', timeout=15)
        conns = r.json().get('connections', [])
        return [c for c in conns if c.get('provider') == 'grok-cli']

def add_to_router_single(acc):
    """Add single account to 9Router (for parallel execution)."""
    try:
        r9 = Router9()
        if not r9.login():
            log_no("9router login failed")
            return False

        existing = {c.get('email') for c in r9.list_providers()}
        email = acc.get('email', '')

        if email in existing:
            log_wait(f"{email} already exists"); return False
    except Exception as e:
        log_no(f"9router API error: {e}")
        return False

    # Pick proxy from pool
    proxy_config = None
    proxy_server = None
    if PROXY_POOL:
        proxy_server = PROXY_POOL.get_random_proxy()
        if proxy_server:
            proxy_config = {'server': f'http://{proxy_server}'}
        else:
            log_wait("no available proxy - using direct connection")

    # Generate random user agent
    user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    ]
    user_agent = random.choice(user_agents)

    try:
        with sync_playwright() as p:
            launch_kwargs = {
                'user_data_dir': f'/tmp/grok-router-{int(time.time()*1000)}-{random.randint(1000,9999)}',
                'headless': False,
                'no_viewport': True,
                'executable_path': CHROME_BIN,
                'user_agent': user_agent,
                'args': [
                    '--no-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-blink-features=AutomationControlled',
                    '--use-fake-ui-for-media-stream',
                    '--use-fake-device-for-media-stream',
                    f'--user-agent={user_agent}',
                ],
                'ignore_default_args': ['--enable-automation'],
            }
            if proxy_config:
                launch_kwargs['proxy'] = proxy_config

            log_wait(f"launching browser (proxy: {proxy_server or 'none'})")
            ctx = p.chromium.launch_persistent_context(**launch_kwargs)
            try:
                ctx.clear_cookies()
                cookies = acc.get('sso_cookies', [])
                if cookies:
                    safe = []
                    for c in cookies:
                        cc = dict(c)
                        if not cc.get('domain'):
                            continue
                        ss = cc.get('sameSite','Lax')
                        if ss not in ('Strict','Lax','None'):
                            ss = 'Lax'
                        cc['sameSite'] = ss
                        safe.append(cc)
                    ctx.add_cookies(safe)

                d = r9.device_code()
                verify_url = d['verification_uri_complete']

            page = ctx.new_page()
            page.goto(verify_url, wait_until='domcontentloaded', timeout=45000)
            time.sleep(3)

            has_login = page.evaluate("!!document.querySelector('input[type=email], input[type=password]')")
            if has_login:
                log_no(f"{email} SSO expired"); page.close(); ctx.close(); return False

            try:
                page.get_by_role('button', name=re.compile(r'Continue', re.I)).click(timeout=5000)
                time.sleep(3)
            except:
                pass

            try:
                page.get_by_role('button', name=re.compile(r'Allow', re.I)).click(timeout=8000)
                time.sleep(2)
            except:
                log_no(f"{email} Allow button not found"); page.close(); ctx.close(); return False

            time.sleep(3); page.close()

            for _ in range(60):
                res = r9.poll(d['device_code'], d['code_verifier'])
                if res.get('success'):
                    log_ok(f"{email} added ✓")
                    ctx.close()
                    # Report proxy success
                    if PROXY_POOL and proxy_server:
                        PROXY_POOL.report_success(proxy_server)
                    return True
                if not res.get('pending'):
                    log_no(f"{email} poll error")
                    ctx.close()
                    # Report proxy failure
                    if PROXY_POOL and proxy_server:
                        PROXY_POOL.report_failure(proxy_server)
                    return False
                time.sleep(5)

            log_no(f"{email} poll timeout")
            ctx.close()
            # Report proxy failure on timeout
            if PROXY_POOL and proxy_server:
                PROXY_POOL.report_failure(proxy_server)
            return False
        except Exception as e:
            log_no(f"{email} error: {e}")
            ctx.close()
            # Report proxy failure on exception
            if PROXY_POOL and proxy_server:
                PROXY_POOL.report_failure(proxy_server)
            return False
    except Exception as outer_e:
        # Report proxy failure on outer exception
        if PROXY_POOL and proxy_server:
            PROXY_POOL.report_failure(proxy_server)
        return False

# ── Main signup flow ──────────────────────────────────────────
def signup_one(email_code_pair=None):
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

    ext_path = unlock_turnstile()

    # Pick proxy from pool
    proxy_config = None
    proxy_server = None
    if PROXY_POOL:
        proxy_server = PROXY_POOL.get_random_proxy()
        if proxy_server:
            proxy_config = {'server': f'http://{proxy_server}'}
        else:
            log_wait("no available proxy - using direct connection")

    # Generate random user agent
    user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    ]
    user_agent = random.choice(user_agents)
    log_ok(f"user agent: {user_agent[:50]}...")

    signup_success = False
    try:
        with sync_playwright() as p:
        launch_args = {
            'user_data_dir': f'/tmp/grok-pw-{int(time.time()*1000)}-{random.randint(1000,9999)}',
            'headless': False,
            'no_viewport': True,
            'user_agent': user_agent,
            'args': [
                f'--disable-extensions-except={ext_path}',
                f'--load-extension={ext_path}',
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-blink-features=AutomationControlled',
                '--use-fake-ui-for-media-stream',
                '--use-fake-device-for-media-stream',
                '--disable-webgl',
                '--disable-webgl2',
                f'--user-agent={user_agent}',
            ],
            'ignore_default_args': ['--enable-automation'],
        }
        if CHROME_BIN:
            launch_args['executable_path'] = CHROME_BIN
        if proxy_config:
            launch_args['proxy'] = proxy_config

        log_wait("launching browser...")
        log_wait(f"  Chrome: {CHROME_BIN or 'bundled'}")
        log_wait(f"  Extension: {ext_path}")
        log_wait(f"  Proxy: {proxy_server or 'none'}")
        log_wait(f"  User-Agent: {user_agent[:60]}...")

        ctx = p.chromium.launch_persistent_context(**launch_args)

        page = ctx.new_page()
        page.goto(signup_url, wait_until='domcontentloaded', timeout=60000)
        time.sleep(4)
        log_ok("page loaded")

        # Cookie banner
        try:
            page.get_by_role('button', name='Accept All Cookies').click(timeout=3000)
            time.sleep(0.5)
        except:
            pass

        try:
            page.get_by_text('Sign up with email', exact=False).click(timeout=15000)
            page.wait_for_selector('input[type=email]', timeout=8000)
            time.sleep(2)
            log_ok("email form")
        except Exception as e:
            ctx.close()
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

        page.locator('input[type=email]').fill(addr)
        page.locator('input[type=email]').press('Enter')

        # Wait for OTP input, with fallback to click 'Sign up' button
        try:
            page.wait_for_selector('input[name=code]', timeout=20000)
        except:
            page.get_by_role('button', name='Sign up').click(timeout=3000)
            page.wait_for_selector('input[name=code]', timeout=15000)
        log_ok("email submitted")

        if not code:
            code = wait_for_otp(mail, timeout=120)
            if not code:
                mail.logout(); ctx.close()
                raise RuntimeError("OTP timeout 120s")
        log_ok(f"OTP: {code}")

        code_input = page.locator('input[name=code]').first
        code_input.fill(code, timeout=15000)
        time.sleep(0.3)
        log_wait("submitting OTP...")
        page.keyboard.press('Enter')
        page.wait_for_selector('input[name=givenName]', timeout=20000)
        log_ok("OTP verified")

        local = addr.split('@')[0]
        parts = re.split(r'[._\-]', local)
        given = parts[0].capitalize()
        family = (parts[1] if len(parts) > 1 else 'Xyz').capitalize()

        page.locator('input[name=givenName]').fill(given)
        page.locator('input[name=familyName]').fill(family)
        page.locator('input[name=password]').fill(PASSWORD)
        log_ok("form filled")

        # Turnstile retry loop (max 3 attempts in same browser session)
        turnstile_success = False
        for ts_attempt in range(1, 4):
            # Wait for turnstile token
            log_wait(f"solving turnstile (attempt {ts_attempt}/3)...")

            # Diagnostic: check if extension loaded
            try:
                ext_count = page.evaluate("chrome.runtime ? 1 : 0")
                log_wait(f"  extension API available: {ext_count == 1}")
            except:
                log_no("  could not check extension status")

            # Diagnostic: check turnstile iframe presence
            try:
                iframe_count = page.evaluate("document.querySelectorAll('iframe[src*=\"turnstile\"]').length")
                log_wait(f"  turnstile iframes found: {iframe_count}")
            except:
                pass

            token = ''
            for i in range(10):
                token = page.evaluate("document.querySelector('input[name=cf-turnstile-response]')?.value || ''")
                if token:
                    log_ok(f"turnstile solved (token: {token[:20]}...)")
                    break
                if i == 5:
                    log_wait("  still waiting for turnstile token...")
                time.sleep(1)

            if token:
                turnstile_success = True
                break

            # Turnstile failed - click "Go back" and retry with delay
            log_no(f"turnstile timeout (attempt {ts_attempt}/3)")
            if ts_attempt < 3:
                # Random delay between retries to avoid rate limiting
                retry_delay = random.randint(10, 30)
                log_wait(f"waiting {retry_delay}s before retry...")
                time.sleep(retry_delay)
                try:
                    page.get_by_role('button', name=re.compile(r'Go back', re.I)).click(timeout=5000)
                    log_ok("clicked Go back")
                    time.sleep(2)

                    # Re-input email
                    page.wait_for_selector('input[type=email]', timeout=8000)
                    page.locator('input[type=email]').fill(addr)
                    page.locator('input[type=email]').press('Enter')
                    log_ok("re-submitted email")

                    # Wait for OTP input
                    try:
                        page.wait_for_selector('input[name=code]', timeout=20000)
                    except:
                        page.get_by_role('button', name='Sign up').click(timeout=3000)
                        page.wait_for_selector('input[name=code]', timeout=15000)

                    # Read new OTP from Gmail
                    mail._seen_ids.clear()  # Clear seen IDs to read fresh email
                    new_code = wait_for_otp(mail, timeout=120)
                    if not new_code:
                        mail.logout(); ctx.close()
                        raise RuntimeError("OTP timeout on retry")
                    log_ok(f"new OTP: {new_code}")

                    # Submit OTP
                    code_input = page.locator('input[name=code]').first
                    code_input.fill(new_code, timeout=15000)
                    time.sleep(0.3)
                    page.keyboard.press('Enter')
                    page.wait_for_selector('input[name=givenName]', timeout=20000)
                    log_ok("OTP verified")

                    # Re-fill form
                    page.locator('input[name=givenName]').fill(given)
                    page.locator('input[name=familyName]').fill(family)
                    page.locator('input[name=password]').fill(PASSWORD)
                    log_ok("form re-filled")
                except Exception as e:
                    log_no(f"retry failed: {e}")
                    break

        if not turnstile_success:
            mail.logout(); ctx.close()
            raise RuntimeError("turnstile failed after 3 attempts")

        page.get_by_role('button', name='Complete sign up').click()
        log_ok("submitted")

        # Wait for OAuth page elements to appear (smarter than fixed sleep)
        log_wait("waiting for OAuth page...")
        try:
            # Wait for Continue button or Allow button to appear
            page.wait_for_selector('button:has-text("Continue"), button:has-text("Allow")', timeout=15000)
            log_ok("OAuth page loaded")
        except:
            log_wait("OAuth page detection timeout, continuing...")
        time.sleep(1)

        # Accept cookies if banner appears after redirect
        try:
            page.get_by_role('button', name='Accept All Cookies').click(timeout=2000)
            log_ok("accepted cookies")
            time.sleep(0.5)
        except:
            pass

        # Click Continue button (if present - may auto-continue)
        try:
            page.get_by_role('button', name=re.compile(r'Continue', re.I)).click(timeout=5000)
            log_ok("clicked Continue")
            time.sleep(1)
        except Exception:
            log_wait("Continue button not found or auto-continued")

        # Click Allow button
        try:
            page.get_by_role('button', name=re.compile(r'Allow', re.I)).click(timeout=8000)
            log_ok("clicked Allow")
            time.sleep(1)
        except Exception as e:
            mail.logout(); ctx.close()
            raise RuntimeError(f"Allow button not found: {e}")

        # Close browser immediately after Allow
        log_ok("closing browser...")
        mail.logout()
        ctx.close()

        # Poll 9router with retry mechanism (guaranteed delivery)
        log_wait("polling 9router (guaranteed retry)...")
        poll_success = False
        max_poll_attempts = 20  # 20 attempts × 5s = 100s max

        for attempt in range(1, max_poll_attempts + 1):
            try:
                res = r9.poll(device_code, code_verifier)
                if res.get('success'):
                    log_ok(f"✓ 9router import success (attempt {attempt}/{max_poll_attempts})")
                    poll_success = True
                    break
                if not res.get('pending'):
                    # Not pending but not success = error, retry anyway
                    log_wait(f"poll error (attempt {attempt}/{max_poll_attempts}): {res.get('error', 'unknown')}, retrying...")
                    time.sleep(5)
                    continue
                # Still pending, keep polling
                if attempt % 5 == 0:
                    log_wait(f"still polling... (attempt {attempt}/{max_poll_attempts})")
                time.sleep(5)
            except Exception as poll_err:
                log_wait(f"poll exception (attempt {attempt}/{max_poll_attempts}): {poll_err}, retrying...")
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

        mail.logout()
        ctx.close()

        # Report proxy success
        if PROXY_POOL and proxy_server:
            PROXY_POOL.report_success(proxy_server)

        return data

    except Exception as e:
        # Report proxy failure
        if PROXY_POOL and proxy_server:
            PROXY_POOL.report_failure(proxy_server)
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
    print(f"{CYN}║{RST} {BOLD}GROK SIGNUP + 9ROUTER AUTO-IMPORT{RST}")
    print(f"{CYN}{'='*74}{RST}")
    print(f"{CYN}║{RST} Mode: {'INFINITE' if max_accounts <= 0 else f'{max_accounts} accounts'}")
    print(f"{CYN}║{RST} Batch Size: {BATCH_SIZE}")
    print(f"{CYN}║{RST} Chrome: {CHROME_BIN or 'bundled'}")
    print(f"{CYN}║{RST} Auto-Import: {'YES' if auto_add else 'NO'}")

    # Proxy pool stats
    if PROXY_POOL:
        stats = PROXY_POOL.get_stats()
        print(f"{CYN}║{RST} Proxy Pool: {stats['total']} total, {stats['available']} available")
    else:
        print(f"{YEL}║{RST} Proxy Pool: disabled (PROXIES env not set)")

    print(f"{CYN}║{RST} Extension: {TS_DIR}")
    print(f"{CYN}║{RST} Account Retries: {MAX_ACCOUNT_RETRIES}")
    print(f"{CYN}║{RST} Delay Between Accounts: {DELAY_SECONDS}s")
    print(f"{CYN}║{RST} Pause Between Batches: {PAUSE_SECONDS}s")

    # Diagnostic: check extension files
    if (TS_DIR / 'manifest.json').exists():
        print(f"{GRN}║{RST} ✓ turnstilePatch extension found")
    else:
        print(f"{RED}║{RST} ✗ turnstilePatch extension MISSING")

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
                    acc = signup_one(email_code_pair)
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

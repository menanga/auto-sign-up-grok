#!/usr/bin/env python3
"""grok-signup-nodriver.py — Auto-register Grok (x.ai) accounts.

Runs inside Docker under xvfb; starts a fresh Chromium profile for every account
and pushes successful accounts into a 9router instance.
Environment / .env controls (see .env.example):
  GMAIL_USER, GMAIL_APP_PASSWORD, GMAIL_DOMAINS, PASSWORD,
  ROUTER9_URL, ROUTER9_PASS,
  MAX_ACCOUNTS, BATCH_SIZE, PAUSE_SECONDS, MAX_ACCOUNT_RETRIES,
  CHROME_BIN, CAPTCHA_API_KEY (optional), CAPTCHA_PROVIDER (optional)
"""
import asyncio
import json
import os
import random
import re
import string
import sys
import tempfile
import time
from email import message_from_bytes
from pathlib import Path

import imaplib
import nodriver as uc
import curl_cffi.requests as creq

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
CHROME_BIN = _env_or('CHROME_BIN', '/usr/bin/chromium')
SIGNUP = 'https://accounts.x.ai/sign-up?redirect=grok-com'
OUT = Path('/app/sso.txt') if os.path.exists('/app') else Path('sso.txt')

MAX_ACCOUNTS = int(_env_or('MAX_ACCOUNTS', '1'))    # <= 0 = infinite
BATCH_SIZE = max(1, int(_env_or('BATCH_SIZE', '1')))
PAUSE_SECONDS = int(_env_or('PAUSE_SECONDS', '10'))
DELAY_SECONDS = int(_env_or('DELAY_SECONDS', '5'))
MAX_ACCOUNT_RETRIES = max(1, int(_env_or('MAX_ACCOUNT_RETRIES', '3')))
AUTO_ADD = os.environ.get('AUTO_ADD', 'false').lower() in ('1','true','yes')

_used_addrs = set()
GRN, RED, YEL, CYN, RST = '\033[32m', '\033[31m', '\033[33m', '\033[36m', '\033[0m'

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
    raise RuntimeError('could not generate a unique email address')

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
        # Try specific patterns first, then broad
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
                    return code

                # Fallback: try body
                text = self._body_text(msg)
                if text:
                    log_wait(f"Body snippet: {text[:100]}")
                    code = self._extract_code(text)
                    if code:
                        log_ok(f"✓ Extracted OTP: {code} from BODY")
                        self._seen_ids.add(mid)
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

async def wait_for_otp(mail: GmailIMAP, timeout: int = 120):
    t = time.time()
    while time.time() - t < timeout:
        code = mail.peek_code()
        if code:
            return code
        await asyncio.sleep(0.5)
    return None

# ── 9Router helper ─────────────────────────────────────────────
class Router9:
    def __init__(self):
        self.s = creq.Session()
        self.s.headers.update({'Accept':'application/json','Content-Type':'application/json'})

    def login(self):
        r = self.s.post(f'{ROUTER9}/api/auth/login', json={'password':ROUTER9_PASS}, timeout=15)
        return r.json().get('success', False)

    def device_code(self):
        r = self.s.get(f'{ROUTER9}/api/oauth/grok-cli/device-code', timeout=10)
        return r.json()

    def poll(self, device_code, code_verifier):
        r = self.s.post(f'{ROUTER9}/api/oauth/grok-cli/poll',
                        json={'deviceCode': device_code, 'codeVerifier': code_verifier}, timeout=10)
        return r.json()

    def list_providers(self):
        r = self.s.get(f'{ROUTER9}/api/providers', timeout=15)
        conns = r.json().get('connections', [])
        return [c for c in conns if c.get('provider') == 'grok-cli']

def add_to_router(accounts: list):
    if not accounts:
        return
    print(f"\n {CYN}─── [ 9ROUTER ADD ] ─{RST}")
    r9 = Router9()
    if not r9.login():
        log_no("9router login failed"); return
    log_ok("9router login")
    existing = {c.get('email') for c in r9.list_providers()}

    from playwright.sync_api import sync_playwright
    profile = str(Path(tempfile.gettempdir()) / f"grok-router-{int(time.time())}")
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=profile,
            headless=False,
        no_sandbox=True,
            executable_path=CHROME_BIN,
            args=['--no-sandbox','--disable-dev-shm-usage','--disable-blink-features=AutomationControlled',
                  '--window-size=1280,1024'],
            viewport={'width':1280,'height':1024},
            ignore_default_args=['--enable-automation'],
        )
        added = skipped = failed = 0
        for i, acc in enumerate(accounts):
            email = acc.get('email','')
            print(f"\n  [{i+1}/{len(accounts)}] {email}", flush=True)
            if email in existing:
                log_wait("sudah ada, skip"); skipped += 1; continue
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
                user_code = d['user_code']
                verify_url = d['verification_uri_complete']
                log_wait(f"user_code: {user_code}")

                page = ctx.new_page()
                page.goto(verify_url, wait_until='domcontentloaded', timeout=45000)
                time.sleep(3)
                has_login_input = page.evaluate("!!document.querySelector('input[type=email], input[type=password]')")
                if has_login_input:
                    log_no("SSO expired, need login"); page.close(); failed += 1; continue

                try:
                    page.get_by_role('button', name=re.compile(r'Continue', re.I)).click(timeout=5000)
                    time.sleep(3)
                except Exception:
                    pass

                try:
                    page.get_by_role('button', name=re.compile(r'Allow', re.I)).click(timeout=8000)
                    log_ok("allow"); time.sleep(2)
                except Exception:
                    log_no("tombol Allow gak ketemu")
                    page.close(); failed += 1; continue

                time.sleep(3); page.close()

                for _ in range(60):
                    res = r9.poll(d['device_code'], d['code_verifier'])
                    if res.get('success'):
                        log_ok("added to 9router ✓"); added += 1; break
                    if not res.get('pending'):
                        log_no(f"poll error: {res.get('error')}"); failed += 1; break
                    time.sleep(5)
                else:
                    log_no("poll timeout 5min"); failed += 1
            except Exception as e:
                log_no(f"err: {e}"); failed += 1
        ctx.close()
    print(f"\n  {GRN}added{RST}: {added}  {YEL}skipped{RST}: {skipped}  {RED}failed{RST}: {failed}", flush=True)

# ── Cloudflare Turnstile mitigation ───────────────────────────
async def solve_turnstile_with_mitigation(page, retries: int = 3):
    """Try nodriver verify_cf, then optional external solver, retrying."""
    for attempt in range(1, retries + 1):
        log_wait(f"Turnstile solve attempt {attempt}/{retries}")
        token = await solve_turnstile(page)
        if token:
            log_ok(f"Turnstile token: {token[:20]}...")
            return token
        if attempt < retries:
            backoff = 3 + attempt * 2 + random.uniform(0, 2)
            log_wait(f"backoff {backoff:.1f}s")
            await asyncio.sleep(backoff)
            try:
                await page.evaluate('location.reload()')
                await asyncio.sleep(3)
            except Exception:
                pass
    return ""

# ── Main signup flow (one account) ────────────────────────────
async def signup_one(email_code_pair=None):
    profile = Path(tempfile.gettempdir()) / f"grok-nd-{int(time.time()*1000)}-{random.randint(1000,9999)}"
    browser = await uc.start(
        user_data_dir=str(profile),
        headless=False,
        no_sandbox=True,
        browser_executable_path=CHROME_BIN,
        sandbox=False,
        browser_args=['--no-sandbox','--disable-dev-shm-usage','--disable-blink-features=AutomationControlled',
                      '--disable-background-networking','--window-size=1280,1024'],
    )
    try:
        page = await browser.get(SIGNUP)
        await asyncio.sleep(4)

        # Cookie banner
        for text in ['Accept All Cookies', 'Allow All', 'Agree', 'Confirm My Choices']:
            try:
                btn = await page.find(text, timeout=3)
                await btn.click(); await asyncio.sleep(0.5)
                break
            except Exception:
                continue

        # Open email form
        btn = await page.find('Sign up with email', timeout=15)
        await btn.click()
        await asyncio.sleep(2)
        log_ok("email form opened")

        # Reuse existing mail+code if retrying, otherwise create
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

        email_input = await page.select('input[type=email]', timeout=15)
        await email_input.click()
        await email_input.send_keys(addr)
        await asyncio.sleep(0.5)

        submit_btn = await page.find('Sign up', timeout=10)
        await submit_btn.click()
        log_ok("clicked Sign up")
        await asyncio.sleep(2)

        code_input = await page.select('input[name=code]', timeout=20000)
        log_ok("email submitted")

        if not code:
            code = await wait_for_otp(mail, timeout=120)
            if not code:
                raise RuntimeError("OTP timeout 120s")
        log_ok(f"OTP: {code}")

        await code_input.click()
        await code_input.send_keys(code)
        await asyncio.sleep(0.3)
        log_wait("submitting OTP...")
        await page.evaluate("document.querySelector('input[name=code]').dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', code:'Enter', bubbles:true}))")
        await asyncio.sleep(3)

        # Debug: check for error messages
        try:
            error_text = await page.evaluate("document.body.innerText")
            if 'invalid' in error_text.lower() or 'incorrect' in error_text.lower():
                log_no(f"OTP error detected: {error_text[:200]}")
        except:
            pass

        await page.select('input[name=givenName]', timeout=20000)
        log_ok("OTP verified")

        local = addr.split('@')[0]
        parts = re.split(r'[._\-]', local)
        given = parts[0].capitalize()
        family = (parts[1] if len(parts) > 1 else 'Xyz').capitalize()

        await (await page.select('input[name=givenName]')).send_keys(given)
        await (await page.select('input[name=familyName]')).send_keys(family)
        await (await page.select('input[name=password]')).send_keys(PASSWORD)
        log_ok("form filled")

        # Solve Turnstile
        token = await solve_turnstile_with_mitigation(page, retries=MAX_ACCOUNT_RETRIES)
        if not token:
            # Preserve data so main can retry from start with same alias
            raise TurnstileRetry(mail, code)

        # Submit registration
        try:
            complete = await page.find('Complete sign up', timeout=10)
            await complete.scroll_into_view(); await asyncio.sleep(0.5)
            await complete.click()
            log_ok("submitted")
        except Exception:
            submit = await page.select('button[type=submit]', timeout=5)
            await submit.scroll_into_view(); await asyncio.sleep(0.5)
            await submit.click()
            log_ok("submitted (fallback)")

        # Wait for redirect / success indicator
        final_url = ''
        success = False
        for i in range(30):
            await asyncio.sleep(2)
            final_url = await page.evaluate('location.href')
            if 'grok.com' in final_url or 'accounts.x.ai/authorize' in final_url:
                log_ok(f"redirect: {final_url}")
                success = True
                break
            txt = await page.evaluate('document.body.innerText')
            lower = txt.lower()
            for err in ['too weak','already','invalid','try again','failed','unusual activity']:
                if err in lower:
                    raise RuntimeError(f"page error: {txt[:200]}")

        raw_cookies = []
        try:
            raw_cookies = await page.send(uc.cdp.network.get_cookies())
        except Exception:
            try:
                raw_cookies = await page.evaluate("""
                document.cookie.split('; ').map(c => {
                    const [k,...v] = c.split('=');
                    return {name:k, value:v.join('='), domain:location.hostname};
                })
                """)
            except Exception:
                pass

        sso_cookies = []
        try:
            if isinstance(raw_cookies, list):
                for c in raw_cookies:
                    if isinstance(c, dict):
                        sso_cookies.append(c)
                    elif hasattr(c,'name'):
                        sso_cookies.append({'name':c.name,'value':c.value,'domain':getattr(c,'domain',''),'path':getattr(c,'path','/')})
        except Exception:
            pass

        if not success and not sso_cookies:
            raise RuntimeError(f"no redirect (last: {final_url})")

        data = {
            'email': addr,
            'password': PASSWORD,
            'code': code,
            'sso_cookies': sso_cookies,
            'final_url': final_url,
            'timestamp': int(time.time()),
        }
        OUT.parent.mkdir(parents=True, exist_ok=True)
        with open(OUT, 'a') as f:
            f.write(json.dumps(data) + '\n')
        log_ok(f"saved → {OUT}")

        try:
            mail.logout()
        except Exception:
            pass
        return data
    finally:
        try:
            browser.stop()
        except Exception:
            pass

# ── Infinite runner (mirrors bulk-cf style) ──────────────────
async def run_accounts():
    auto_add = AUTO_ADD or '--auto-add' in sys.argv
    max_accounts = MAX_ACCOUNTS
    total = ok_n = fail_n = 0
    router_semaphore = asyncio.Semaphore(1)

    async def router_worker(acc):
        try:
            await asyncio.to_thread(add_to_router, [acc])
        except Exception as e:
            log_no(f"9router add error: {e}")

    print(f"{CYN}─── [ GROK SIGNUP (nodriver) ] ───{RST}", flush=True)
    print(f"CHROME_BIN={CHROME_BIN}, MAX_ACCOUNTS={max_accounts}, BATCH={BATCH_SIZE}", flush=True)

    while max_accounts <= 0 or total < max_accounts:
        batch_target = min(BATCH_SIZE, (max_accounts - total) if max_accounts > 0 else BATCH_SIZE)
        for i in range(batch_target):
            total += 1
            t0 = time.time()
            email_code_pair = None
            last_ex = None
            for attempt in range(1, MAX_ACCOUNT_RETRIES + 1):
                try:
                    acc = await signup_one(email_code_pair)
                    ok_n += 1
                    log_ok(f"{acc['email']} success in {time.time()-t0:.1f}s")
                    if auto_add:
                        asyncio.create_task(router_worker(acc))
                    break
                except TurnstileRetry as e:
                    email_code_pair = (e.mail, e.code)
                    last_ex = e
                    log_no(f"Turnstile failed attempt {attempt}/{MAX_ACCOUNT_RETRIES}, retrying with same data...")
                except Exception as e:
                    last_ex = e
                    fail_n += 1
                    log_no(f"account #{total} failed: {e}")
                    break
            else:
                # Retries exhausted
                fail_n += 1
                log_no(f"account #{total} failed after {MAX_ACCOUNT_RETRIES} Turnstile retries")

            log_wait(f"done account #{total}; delaying {DELAY_SECONDS}s")
            await asyncio.sleep(DELAY_SECONDS)

        if max_accounts > 0 and total >= max_accounts:
            break
        log_wait(f"batch done; sleeping {PAUSE_SECONDS}s before next batch")
        await asyncio.sleep(PAUSE_SECONDS)

    print(f"\n  {GRN}OK{RST}: {ok_n}  {RED}FAIL{RST}: {fail_n}  {CYN}TOTAL{RST}: {total}", flush=True)

if __name__ == '__main__':
    try:
        asyncio.run(run_accounts())
    except KeyboardInterrupt:
        print(f"\n{YEL}stopped by user{RST}")

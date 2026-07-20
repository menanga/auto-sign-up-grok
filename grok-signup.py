#!/usr/bin/env python3
"""grok-signup.py — Auto-register akun Grok (x.ai). Playwright + channel='chrome' + xvfb."""
import sys, time, re, json, os, tempfile
from pathlib import Path
from playwright.sync_api import sync_playwright
import curl_cffi.requests as creq

IS_WIN = sys.platform == 'win32'

# ── Config (from .env) ────────────────────────────────────────
_env = {}
_envfile = Path(__file__).parent / '.env'
if _envfile.exists():
    for line in _envfile.read_text().splitlines():
        if '=' in line and not line.startswith('#'):
            k, v = line.split('=', 1)
            _env[k.strip()] = v.strip()

def _env_or(key, default): return _env.get(key, default)

PASSWORD = _env_or('PASSWORD', 'change-me')
TS_DIR   = Path('turnstilePatch').resolve()
OUT      = Path('sso.txt')
SIGNUP   = 'https://accounts.x.ai/sign-up?redirect=grok-com'
MAILLDEZ = _env_or('MAILLDEZ_URL', 'https://your-mail-api.example')
DOMAINS  = _env_or('MAILLDEZ_DOMAINS', 'example.com').split(',')
ROUTER9  = _env_or('ROUTER9_URL', 'https://your-9router.example')
ROUTER9_PASS = _env_or('ROUTER9_PASS', 'change-me')
_domain_idx = 0
def next_domain():
    global _domain_idx
    d = DOMAINS[_domain_idx % len(DOMAINS)]
    _domain_idx += 1
    return d

def unlock_turnstile():
    """Return path to turnstilePatch directory (plaintext script.js + manifest.json)."""
    if not (TS_DIR / 'script.js').exists() or not (TS_DIR / 'manifest.json').exists():
        raise RuntimeError(f"missing turnstilePatch/script.js or manifest.json di {TS_DIR}")
    return str(TS_DIR)

# ── ANSI ──────────────────────────────────────────────────────
GRN,RED,YEL,CYN,BLU,MAG,DIM,BOLD,RST = \
    '\033[32m','\033[31m','\033[33m','\033[36m','\033[34m','\033[35m','\033[2m','\033[1m','\033[0m'
SP = '⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
W = 74
BAR_FILLED, BAR_EMPTY = '■', '□'

def clear_line(): sys.stdout.write('\r\033[K'); sys.stdout.flush()

def box(lines, color=CYN):
    # Top border
    print(f"{color}{'─'*W}{RST}")
    for l in lines:
        print(f"{color}{l}{RST}")
    print(f"{color}{'─'*W}{RST}")

def header(count, total, ok_n, fail_n, t_start):
    elapsed = time.time() - t_start
    print(f"\n{CYN} ─── [ GROK SIGNUP RUNNER ] ──{'─'*(W-31)}{RST}")
    state = f"[●] Running: {count}/{total} Queue" if count < total else f"[✓] Done: {total}/{total}"
    rate = f"{elapsed:.1f}s"
    print(f"  {state}  |  [✓] {ok_n} SUCCESS  |  [×] {fail_n} FAILED  |  {rate}")
    print(f"{CYN}{'─'*W}{RST}")

def table_sep():
    print(f"  {DIM}{'─'*70}{RST}")

def row(idx, email, step_n, step_msg, status, metric):
    print(f"  {DIM}{idx:<3}{RST} {email[:34]:<34} {CYN}[{step_n:02d}]{RST} {step_msg[:18]:<18} {status:<12} {DIM}{metric}{RST}")

def log_line(tag, msg, tag_color=GRN):
    print(f"  {tag_color}│{RST} {tag_color}{tag:<6}{RST} {msg}")

def prog_bar(cur, total, width=30):
    if total == 0: return ""
    filled = int(cur / total * width)
    return f"[{GRN}{BAR_FILLED*filled}{RST}{DIM}{BAR_EMPTY*(width-filled)}{RST}]"

def footer(ok_n, total, t_start):
    print(f"\n {DIM}[ Diagnostics ]{'─'*(W-17)}{RST}")
    rate = ok_n / max(1, (time.time()-t_start)/60)
    health = ok_n / max(1, total) * 100
    print(f"  Health {health:.1f}%  |  Speed {rate:.1f}/m  |  Errors {total - ok_n}")
    bar = prog_bar(ok_n, total, width=40)
    print(f"  TOTAL {bar} {ok_n}/{total} {int(ok_n/total*100) if total else 0}%")

def step(n, msg):
    print(f"\n  {CYN}[{n:02d}]{RST} {msg}")

def ok(msg):    print(f"    {GRN}✓{RST} {msg}")
def no(msg):    print(f"    {RED}✗{RST} {msg}")
def wait(msg):  print(f"    {YEL}→{RST} {msg}")

# ── Temp Mail (MAILLDEZ) ──────────────────────────────────────
class Mail:
    def __init__(self):
        self.s = creq.Session()
        self.s.headers.update({'Accept':'application/json','Content-Type':'application/json'})
    def create(self):
        sid = self.s.get(f'{MAILLDEZ}/api/session', timeout=15).json()['sessionId']
        self.s.headers['x-session-id'] = sid
        self.domain = next_domain()
        r = self.s.post(f'{MAILLDEZ}/api/inboxes', json={'domain':self.domain}, timeout=15)
        self.addr = r.json()['address']; return self.addr
    def peek_code(self):
        for m in self.s.get(f'{MAILLDEZ}/api/inboxes/{self.addr}/messages', timeout=15).json() or []:
            for txt in (m.get('subject',''), m.get('body','')):
                g = re.search(r'code:\s*([A-Z0-9]{3}-[A-Z0-9]{3})', txt, re.I)
                if g: return g.group(1).replace('-','')
                g = re.search(r'code:\s*([A-Z0-9]{6})', txt, re.I)
                if g: return g.group(1)
        return None
    def wait_code(self, timeout=120):
        t = time.time()
        while time.time() - t < timeout:
            c = self.peek_code()
            if c: return c
            time.sleep(4)
        return None

# ── 9Router ──────────────────────────────────────────────────
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

# ── Main ──────────────────────────────────────────────────────
def main():
    args = sys.argv[1:]
    # Mode: --router [N]  → add akun dari sso.txt ke 9router (skip signup)
    if args and args[0] == '--router':
        accounts = []
        with open(OUT) as f:
            for l in f:
                if l.strip() and '"email"' in l:
                    try: accounts.append(json.loads(l))
                    except: pass
        if len(args) > 1:
            n = int(args[1])
            accounts = accounts[-n:]
        if not accounts:
            no("gak ada akun di sso.txt"); return
        wait(f"{len(accounts)} akun di sso.txt")
        add_to_router(accounts)
        return

    count = int(args[0]) if args else 1
    t_start = time.time()
    header(0, count, 0, 0, t_start)
    profile = str(Path(tempfile.gettempdir()) / f"grok-pw-{int(time.time())}")
    results = []
    ok_n = 0; fail_n = 0
    log_lines = []
    print(f"\n  {CYN}load turnstile patch...{RST}")
    try:
        ext_path = unlock_turnstile()
    except Exception as e:
        no(f"turnstile load: {e}"); return
    ok(f"patch → {ext_path}")
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=profile, headless=False, channel='chrome',
            args=['--no-sandbox','--disable-dev-shm-usage','--disable-blink-features=AutomationControlled',
                  '--window-size=1280,1024',
                  f'--load-extension={ext_path}',
                  f'--disable-extensions-except={ext_path}'],
            viewport={'width':1280,'height':1024},
            ignore_default_args=['--enable-automation'],
        )
        for i in range(count):
            t_acc = time.time()
            try:
                res = run_one(ctx)
                results.append(res)
                ok_n += 1
                elapsed = f"{time.time()-t_acc:.1f}s"
                table_sep()
                row(i+1, res['email'], 9, 'done', f"{GRN}SUCCESS{RST}", elapsed)
                table_sep()
                log_lines.append((f"[{i+1:03d}] {res['email']} → grok.com ({elapsed})", GRN, 'DONE'))
            except Exception as e:
                fail_n += 1
                elapsed = f"{time.time()-t_acc:.1f}s"
                table_sep()
                row(i+1, '—failed—', 0, 'error', f"{RED}FAILED{RST}", elapsed)
                table_sep()
                log_lines.append((f"[{i+1:03d}] {e} ({elapsed})", RED, 'FAIL'))
                results.append({'error': str(e)})
            try: ctx.clear_cookies()
            except: pass
            # live stats
            print(f"  {DIM}[{ok_n}✓ {fail_n}×]  queue: {count-i-1}  elapsed: {time.time()-t_start:.0f}s{RST}")
        ctx.close()
    # Log box di akhir
    print(f"\n {CYN}┌── [ SYSTEM LOGS ] ──{'─'*(W-21)}{RST}")
    for msg, color, tag in log_lines:
        print(f" {CYN}│{RST} {color}{tag:<6}{RST} {msg}")
    print(f" {CYN}└{'─'*(W-2)}{RST}")
    footer(ok_n, count, t_start)
    # Prompt add ke 9router
    success_accs = [r for r in results if 'email' in r]
    if success_accs:
        print()
        try:
            ans = input(f"  {YEL}?{RST} Add {len(success_accs)} akun ke 9router? [y/N] ").strip().lower()
        except EOFError:
            ans = ''
        if ans == 'y':
            add_to_router(success_accs)

# ── Flow ─────────────────────────────────────────────────────
STEPS = [
    'open page', 'email form', 'create mail', 'wait otp',
    'verify otp', 'fill form', 'solve turnstile', 'submit', 'redirect', 'done',
]

def add_to_router(accounts):
    print(f"\n {CYN}─── [ 9ROUTER ADD ] ──{'─'*(W-21)}{RST}")
    r9 = Router9()
    if not r9.login():
        no("9router login failed"); return
    ok("9router login")
    existing = {c.get('email') for c in r9.list_providers()}
    ok(f"existing grok-cli: {len(existing)}")

    profile = str(Path(tempfile.gettempdir()) / f"grok-router-{int(time.time())}")
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=profile, headless=False, channel='chrome',
            args=['--no-sandbox','--disable-dev-shm-usage','--disable-blink-features=AutomationControlled',
                  '--window-size=1280,1024'],
            viewport={'width':1280,'height':1024},
            ignore_default_args=['--enable-automation'],
        )
        added = 0; skipped = 0; failed = 0
        for i, acc in enumerate(accounts):
            email = acc['email']
            print(f"\n  {DIM}[{i+1}/{len(accounts)}]{RST} {email}")
            if email in existing:
                wait("sudah ada, skip")
                skipped += 1; continue
            try:
                # Inject SSO cookies ke browser context (Playwright-compatible)
                pw_cookies = []
                for c in acc.get('sso_cookies', []):
                    cc = dict(c)
                    if not cc.get('domain'): continue
                    ss = cc.get('sameSite','Lax')
                    if ss not in ('Strict','Lax','None'): ss = 'Lax'
                    cc['sameSite'] = ss
                    pw_cookies.append(cc)
                ctx.clear_cookies()
                ctx.add_cookies(pw_cookies)
                # Ambil device code
                d = r9.device_code()
                user_code = d['user_code']
                verify_url = d['verification_uri_complete']
                wait(f"user_code: {user_code}")
                # Buka verify URL
                page = ctx.new_page()
                page.goto(verify_url, wait_until='domcontentloaded', timeout=45000)
                time.sleep(3)
                # Cek apakah halaman minta login (gak ada SSO) atau langsung authorize
                # Halaman authorize: ada tombol "Continue" + text "Sign in to Grok Build"
                # Halaman login: ada input email/password
                has_login_input = page.evaluate("!!document.querySelector('input[type=email], input[type=password]')")
                if has_login_input:
                    no("SSO expired, need login")
                    page.close(); failed += 1; continue
                # Klik tombol Continue (halaman 1: verify code)
                try:
                    page.get_by_role('button', name='Continue', exact=False).click(timeout=5000)
                    clicked = 'continue'
                    time.sleep(3)
                except:
                    clicked = None
                if clicked:
                    ok(f"continue")
                    # Halaman 2: consent — klik Allow
                    try:
                        page.get_by_role('button', name='Allow', exact=True).click(timeout=8000)
                        ok("allow")
                        time.sleep(2)
                    except:
                        try:
                            page.get_by_role('button', name='Allow All', exact=True).click(timeout=3000)
                            ok("allow all")
                            time.sleep(2)
                        except:
                            no("tombol Allow gak ketemu")
                            page.close(); failed += 1; continue
                time.sleep(3)
                page.close()
                # Poll sampai sukses (interval 5s, max 60 tries = 5 min)
                for _ in range(60):
                    res = r9.poll(d['device_code'], d['codeVerifier'])
                    if res.get('success'):
                        ok(f"added to 9router ✓")
                        added += 1; break
                    elif not res.get('pending'):
                        no(f"poll error: {res.get('error')}")
                        failed += 1; break
                    time.sleep(5)
                else:
                    no("poll timeout 5min"); failed += 1
            except Exception as e:
                no(f"err: {e}"); failed += 1
        ctx.close()
    print(f"\n {CYN}─── [ 9ROUTER DONE ] ──{'─'*(W-21)}{RST}")
    print(f"  {GRN}added{RST}: {added}  {YEL}skipped{RST}: {skipped}  {RED}failed{RST}: {failed}")

def run_one(ctx):
    page = ctx.new_page()
    page.set_extra_http_headers({
        'sec-ch-ua': '"Chromium";v="148", "Google Chrome";v="148", "Not-A.Brand";v="99"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"' if IS_WIN else '"Linux"',
        'accept-language': 'en-US,en;q=0.9',
    })
    try:
        return _flow(page)
    finally:
        page.close()

def _flow(page):
    # 1
    step(1, "Open x.ai signup")
    page.goto(SIGNUP, wait_until='domcontentloaded', timeout=45000)
    time.sleep(3)
    try: page.get_by_role('button', name='Accept All Cookies').click(timeout=3000); time.sleep(0.5)
    except: pass
    ok("page loaded")

    # 2
    step(2, "Sign up with email")
    page.get_by_text('Sign up with email').click(timeout=8000)
    page.wait_for_selector('input[type=email]', timeout=8000)
    ok("email form")

    # 3
    step(3, "Create temp email")
    mail = Mail(); addr = mail.create()
    wait(f"{addr}")
    page.locator('input[type=email]').fill(addr)
    page.locator('input[type=email]').press('Enter')
    try:
        page.wait_for_selector('input[name=code]', timeout=20000)
    except:
        page.get_by_role('button', name='Sign up').click(timeout=3000)
        page.wait_for_selector('input[name=code]', timeout=15000)
    ok("email submitted")

    # 4
    step(4, "Wait for OTP")
    t = time.time(); sp = 0
    code = None
    while time.time() - t < 120:
        code = mail.peek_code()
        if code: break
        sys.stdout.write(f"\r    {CYN}{SP[sp % len(SP)]}{RST} waiting OTP {int(time.time()-t)}s")
        sys.stdout.flush(); sp += 1; time.sleep(0.3)
    clear_line()
    if not code: raise RuntimeError("OTP timeout 120s")
    ok(f"OTP: {code}")

    # 5
    step(5, "Submit OTP")
    page.locator('input[name=code]').first.fill(code, timeout=15000)
    time.sleep(0.3)
    page.keyboard.press('Enter')
    page.wait_for_selector('input[name=givenName]', timeout=20000)
    ok("verified")

    # 6
    step(6, "Fill name & password")
    local = addr.split('@')[0]
    parts = re.split(r'[._\-]', local)
    given  = parts[0].capitalize()
    family = (parts[1] if len(parts) > 1 else 'Xyz').capitalize()
    wait(f"{given} {family}")
    page.locator('input[name=givenName]').fill(given)
    page.locator('input[name=familyName]').fill(family)
    page.locator('input[name=password]').fill(PASSWORD)
    ok("form filled")

    # 7
    step(7, "Solve turnstile & submit")
    tok = ''
    for _ in range(40):
        tok = page.evaluate("document.querySelector('input[name=cf-turnstile-response]')?.value || ''")
        if tok: break
        time.sleep(1)
    if not tok: raise RuntimeError("Turnstile timeout 40s")
    ok(f"turnstile solved")
    # progress bar effect
    for i in range(8):
        sys.stdout.write(f"\r    {CYN}submitting {GRN}{BAR_FILLED*(i+1)}{DIM}{BAR_EMPTY*(7-i)}{RST}")
        sys.stdout.flush(); time.sleep(0.08)
    clear_line()
    page.get_by_role('button', name='Complete sign up').click()
    ok("submitted")

    # 8
    step(8, "Redirect → grok.com")
    last_body = ""
    for i in range(30):
        time.sleep(2)
        try: url = page.url
        except: continue
        if 'grok.com' in url:
            ok(f"→ {url}")
            break
        try:
            txt = page.evaluate("document.body.innerText")
            for err in ['too weak','already','invalid','try again','failed']:
                if err.lower() in txt.lower() and err not in last_body:
                    no(f"err: …{txt[max(0,txt.lower().find(err)-30):txt.lower().find(err)+50]}…")
            last_body = txt
        except: pass
    else:
        sso = [c for c in page.context.cookies() if 'sso' in c.get('name','').lower()]
        if sso: ok(f"SSO cookies: {[c['name'] for c in sso]}")
        else: raise RuntimeError(f"no redirect (last: {page.url})")

    # 9
    step(9, "Save credentials")
    data = {
        'email': addr, 'password': PASSWORD, 'code': code,
        'sso_cookies': page.context.cookies(), 'final_url': page.url,
        'timestamp': int(time.time()),
    }
    with open(OUT, 'a') as f:
        f.write(json.dumps(data) + '\n')
    ok(f"saved → {OUT}")
    return data

if __name__ == '__main__':
    main()

"""
Harder evaluation set (v2) for PR Sentinel.

Differences from v1:
- Bugs are mostly OUTSIDE the five patterns listed in the security prompt
  (SSRF, missing auth, timing attacks, zip-slip, TLS verification off, ReDoS,
  secret logging, subtle logic bugs, ...).
- Each file has realistic surrounding code, so the bug is not the whole file.
- Clean files contain decoys: code that looks risky but is safe.

Same format as cases.py. `expected` markers must each match exactly one line.
"""

CASES = [
    # ---------------- Security bugs not listed in the prompt ----------------
    dict(id="v2_ssrf", category="ssrf", kind="bug",
         code='''import requests

ALLOWED_SCHEMES = ("http", "https")


def build_headers(agent):
    return {"User-Agent": agent, "Accept": "text/html"}


def link_preview(url):
    """Fetch a page on behalf of a user and return its title."""
    resp = requests.get(url, headers=build_headers("preview-bot"), timeout=5)
    text = resp.text
    start = text.find("<title>")
    end = text.find("</title>")
    if start == -1 or end == -1:
        return None
    return text[start + 7:end].strip()
''',
         expected=['resp = requests.get(url, headers=build_headers']),

    dict(id="v2_missing_auth", category="missing_auth", kind="bug",
         code='''USERS = {}


def require_admin(user):
    if not user or not user.get("is_admin"):
        raise PermissionError("admin only")


def list_users(user):
    require_admin(user)
    return list(USERS.values())


def create_user(user, name):
    require_admin(user)
    USERS[name] = {"name": name, "is_admin": False}
    return USERS[name]


def delete_user(user, name):
    return USERS.pop(name, None)
''',
         expected=['def delete_user(user, name):']),

    dict(id="v2_timing", category="timing_attack", kind="bug",
         code='''import hashlib
import hmac


def sign(secret, body):
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def verify_webhook(secret, body, received_signature):
    expected_signature = sign(secret, body)
    if received_signature == expected_signature:
        return True
    return False
''',
         expected=['if received_signature == expected_signature:']),

    dict(id="v2_zipslip", category="zip_slip", kind="bug",
         code='''import os
import zipfile


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def import_archive(zip_path, dest_dir):
    ensure_dir(dest_dir)
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(dest_dir)
    return sorted(os.listdir(dest_dir))
''',
         expected=['archive.extractall(dest_dir)']),

    dict(id="v2_jwt", category="auth_bypass", kind="bug",
         code='''import os

import jwt

SECRET = os.environ["JWT_SECRET"]


def read_claims(token):
    return jwt.decode(token, options={"verify_signature": False})


def current_user_id(token):
    claims = read_claims(token)
    return claims.get("sub")
''',
         expected=['return jwt.decode(token, options={"verify_signature": False})']),

    dict(id="v2_tls", category="tls_disabled", kind="bug",
         code='''import requests


def get_json(url, token):
    headers = {"Authorization": "Bearer " + token}
    resp = requests.get(url, headers=headers, timeout=10, verify=False)
    resp.raise_for_status()
    return resp.json()
''',
         expected=['resp = requests.get(url, headers=headers, timeout=10, verify=False)']),

    dict(id="v2_redos", category="redos", kind="bug",
         code='''import re

PATTERN = re.compile(r"^(a+)+$")


def is_valid_code(user_input):
    """Return True if the code is made only of the letter a."""
    return PATTERN.match(user_input) is not None
''',
         expected=['PATTERN = re.compile(r"^(a+)+$")']),

    dict(id="v2_log_secret", category="secret_logging", kind="bug",
         code='''import logging

logger = logging.getLogger(__name__)


def login(users, username, password):
    logger.info(f"login attempt user={username} password={password}")
    stored = users.get(username)
    return stored is not None and stored == password
''',
         expected=['logger.info(f"login attempt user={username} password={password}")']),

    dict(id="v2_cmd_injection", category="command_injection", kind="bug",
         code='''import subprocess


def ping(host):
    result = subprocess.run(f"ping -c 1 {host}", shell=True, capture_output=True, text=True)
    return result.returncode == 0
''',
         expected=['result = subprocess.run(f"ping -c 1 {host}", shell=True']),

    dict(id="v2_open_redirect", category="open_redirect", kind="bug",
         code='''from flask import Flask, redirect, request

app = Flask(__name__)


@app.route("/login/done")
def login_done():
    next_url = request.args.get("next", "/")
    return redirect(next_url)
''',
         expected=['return redirect(next_url)']),

    # ---------------- Subtle logic bugs ----------------
    dict(id="v2_pagination", category="logic", kind="bug",
         code='''PAGE_SIZE = 20


def paginate(items, page):
    """Return the items for a 1-based page number."""
    offset = page * PAGE_SIZE
    return items[offset:offset + PAGE_SIZE]
''',
         expected=['offset = page * PAGE_SIZE']),

    dict(id="v2_split_bill", category="logic", kind="bug",
         code='''def split_bill(total_cents, people):
    """Split a bill in cents between people; nobody may be over- or under-charged."""
    share = total_cents // people
    return [share] * people
''',
         expected=['share = total_cents // people']),

    dict(id="v2_mutate_loop", category="logic", kind="bug",
         code='''def remove_expired(sessions, now):
    for session in sessions:
        if session["expires_at"] < now:
            sessions.remove(session)
    return sessions
''',
         expected=['sessions.remove(session)']),

    dict(id="v2_falsy_zero", category="logic", kind="bug",
         code='''DEFAULT_TIMEOUT = 30


def fetch(client, url, timeout=None):
    """timeout=0 means: do not wait at all."""
    timeout = timeout or DEFAULT_TIMEOUT
    return client.get(url, timeout=timeout)
''',
         expected=['timeout = timeout or DEFAULT_TIMEOUT']),

    dict(id="v2_timezone", category="logic", kind="bug",
         code='''from datetime import datetime, timedelta


def make_token_expiry(minutes):
    return datetime.utcnow() + timedelta(minutes=minutes)


def is_expired(expiry_utc):
    return datetime.now() > expiry_utc
''',
         expected=['return datetime.now() > expiry_utc']),

    dict(id="v2_swallow_error", category="logic", kind="bug",
         code='''def charge_card(gateway, card, amount):
    try:
        gateway.charge(card, amount)
    except Exception:
        return True
    return True
''',
         expected=['except Exception:']),

    dict(id="v2_cache_key", category="logic", kind="bug",
         code='''_CACHE = {}


def get_profile(db, user_id, path):
    key = f"profile:{path}"
    if key not in _CACHE:
        _CACHE[key] = db.load_profile(user_id)
    return _CACHE[key]
''',
         expected=['key = f"profile:{path}"']),

    dict(id="v2_infinite_retry", category="logic", kind="bug",
         code='''def send_with_retry(client, payload):
    attempts = 0
    while attempts < 3:
        try:
            return client.send(payload)
        except ConnectionError:
            continue
    return None
''',
         expected=['while attempts < 3:']),

    dict(id="v2_race", category="race_condition", kind="bug",
         code='''import threading

counter = 0


def worker(n):
    global counter
    for _ in range(n):
        counter += 1


def run(threads=4, n=100000):
    pool = [threading.Thread(target=worker, args=(n,)) for _ in range(threads)]
    for t in pool:
        t.start()
    for t in pool:
        t.join()
    return counter
''',
         expected=['counter += 1']),

    dict(id="v2_resource_leak", category="resource_leak", kind="bug",
         code='''def read_all(paths):
    contents = []
    for path in paths:
        handle = open(path, encoding="utf-8")
        contents.append(handle.read())
    return contents
''',
         expected=['handle = open(path, encoding="utf-8")']),

    # ---------------- Clean files with decoys ----------------
    dict(id="v2_clean_subprocess", category="clean", kind="clean",
         code='''import re
import subprocess

HOST_RE = re.compile(r"^[A-Za-z0-9.-]{1,253}$")


def ping(host):
    if not HOST_RE.match(host):
        raise ValueError("invalid host")
    result = subprocess.run(["ping", "-c", "1", host], capture_output=True, text=True, check=False)
    return result.returncode == 0
''', expected=[]),

    dict(id="v2_clean_table_const", category="clean", kind="clean",
         code='''TABLE = "orders"


def get_order(cur, order_id):
    cur.execute(f"SELECT * FROM {TABLE} WHERE id = %s", (order_id,))
    return cur.fetchone()
''', expected=[]),

    dict(id="v2_clean_hmac", category="clean", kind="clean",
         code='''import hashlib
import hmac


def verify_webhook(secret, body, received_signature):
    if not received_signature:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(received_signature, expected)
''', expected=[]),

    dict(id="v2_clean_allowlist", category="clean", kind="clean",
         code='''from urllib.parse import urlparse

import requests

ALLOWED_HOSTS = {"api.example.com", "cdn.example.com"}


def fetch(url):
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError("host not allowed")
    return requests.get(url, timeout=5).text
''', expected=[]),

    dict(id="v2_clean_timeout", category="clean", kind="clean",
         code='''DEFAULT_TIMEOUT = 30


def fetch(client, url, timeout=None):
    timeout = DEFAULT_TIMEOUT if timeout is None else timeout
    return client.get(url, timeout=timeout)
''', expected=[]),

    dict(id="v2_clean_files", category="clean", kind="clean",
         code='''def read_all(paths):
    contents = []
    for path in paths:
        with open(path, encoding="utf-8") as handle:
            contents.append(handle.read())
    return contents
''', expected=[]),

    dict(id="v2_clean_lock", category="clean", kind="clean",
         code='''import threading

counter = 0
lock = threading.Lock()


def worker(n):
    global counter
    for _ in range(n):
        with lock:
            counter += 1
''', expected=[]),

    dict(id="v2_clean_pagination", category="clean", kind="clean",
         code='''PAGE_SIZE = 20


def paginate(items, page):
    """Return the items for a 1-based page number."""
    if page < 1:
        raise ValueError("page must be >= 1")
    offset = (page - 1) * PAGE_SIZE
    return items[offset:offset + PAGE_SIZE]
''', expected=[]),

    dict(id="v2_clean_cache_key", category="clean", kind="clean",
         code='''_CACHE = {}


def get_profile(db, user_id):
    key = f"profile:{user_id}"
    if key not in _CACHE:
        _CACHE[key] = db.load_profile(user_id)
    return _CACHE[key]
''', expected=[]),

    dict(id="v2_clean_zip", category="clean", kind="clean",
         code='''import os
import zipfile


def import_archive(zip_path, dest_dir):
    dest_root = os.path.realpath(dest_dir)
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.namelist():
            target = os.path.realpath(os.path.join(dest_root, member))
            if target != dest_root and not target.startswith(dest_root + os.sep):
                raise ValueError("unsafe path in archive")
        archive.extractall(dest_root)
    return sorted(os.listdir(dest_root))
''', expected=[]),
]
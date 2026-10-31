"""
Held-out evaluation set (v3) for PR Sentinel.

RULE: run this set once (3 repeats) AFTER the prompts are finished, and do not
tune prompts against it. If you tune against v3, write a v4 for the final numbers.

About half of the security bugs are in categories that the security prompt does
NOT list (XXE, template injection, mass assignment, CORS, predictable temp files,
debug mode), to measure how well the agents generalize. The logic bugs are new
bug classes. Clean files contain safe lookalikes of the buggy code.
"""

CASES = [
    # ---------------- Security, categories the prompt names (new code) ----------------
    dict(id="v3_sql_orderby", category="sql_injection", kind="bug",
         code='''def list_posts(cur, sort_by):
    """Return post titles ordered by a column chosen by the caller."""
    query = f"SELECT id, title FROM posts ORDER BY {sort_by}"
    cur.execute(query)
    return cur.fetchall()
''',
         expected=['query = f"SELECT id, title FROM posts ORDER BY {sort_by}"']),

    dict(id="v3_os_system", category="command_injection", kind="bug",
         code='''import os


def backup(folder):
    archive = "backup.tgz"
    os.system("tar -czf " + archive + " " + folder)
    return archive
''',
         expected=['os.system("tar -czf "']),

    dict(id="v3_secret_dict", category="hardcoded_secret", kind="bug",
         code='''import os

CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "user": "app",
    "db_password": "P@ssw0rd123",
}


def dsn():
    return "postgresql://{user}:{db_password}@{host}/app".format(**CONFIG)
''',
         expected=['"db_password": "P@ssw0rd123",']),

    dict(id="v3_pickle_cache", category="unsafe_deserialization", kind="bug",
         code='''import pickle


def load_cache(path):
    with open(path, "rb") as handle:
        return pickle.load(handle)
''',
         expected=['return pickle.load(handle)']),

    dict(id="v3_weak_random", category="weak_crypto", kind="bug",
         code='''import random
import string


def new_session_token():
    alphabet = string.ascii_letters + string.digits
    return "".join(random.choice(alphabet) for _ in range(32))
''',
         expected=['return "".join(random.choice(alphabet) for _ in range(32))']),

    dict(id="v3_upload_path", category="path_traversal", kind="bug",
         code='''import os

UPLOAD_DIR = "/srv/uploads"


def save_upload(filename, data):
    target = os.path.join(UPLOAD_DIR, filename)
    with open(target, "wb") as handle:
        handle.write(data)
    return target
''',
         expected=['target = os.path.join(UPLOAD_DIR, filename)']),

    # ---------------- Security, categories NOT named in the prompt ----------------
    dict(id="v3_xxe", category="xxe", kind="bug",
         code='''from lxml import etree


def read_invoice(xml_bytes):
    parser = etree.XMLParser(resolve_entities=True)
    root = etree.fromstring(xml_bytes, parser)
    return root.findtext("total")
''',
         expected=['parser = etree.XMLParser(resolve_entities=True)']),

    dict(id="v3_flask_debug", category="debug_mode", kind="bug",
         code='''from flask import Flask

app = Flask(__name__)


@app.route("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
''',
         expected=['app.run(host="0.0.0.0", port=8000, debug=True)']),

    dict(id="v3_cors", category="cors", kind="bug",
         code='''def add_cors_headers(request, response):
    origin = request.headers.get("Origin")
    response.headers["Access-Control-Allow-Origin"] = origin
    response.headers["Access-Control-Allow-Credentials"] = "true"
    return response
''',
         expected=['response.headers["Access-Control-Allow-Origin"] = origin']),

    dict(id="v3_mass_assignment", category="mass_assignment", kind="bug",
         code='''def update_profile(user, payload):
    """Let a user edit their own profile."""
    user.__dict__.update(payload)
    return user
''',
         expected=['user.__dict__.update(payload)']),

    dict(id="v3_ssti", category="template_injection", kind="bug",
         code='''from flask import render_template_string


def greeting(name):
    return render_template_string("<h1>Hello " + name + "</h1>")
''',
         expected=['return render_template_string("<h1>Hello " + name + "</h1>")']),

    dict(id="v3_tmp_file", category="insecure_temp_file", kind="bug",
         code='''import os


def write_report(text):
    path = "/tmp/report_" + str(os.getpid()) + ".txt"
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path
''',
         expected=['path = "/tmp/report_" + str(os.getpid()) + ".txt"']),

    # ---------------- Logic bugs ----------------
    dict(id="v3_binary_search", category="logic", kind="bug",
         code='''def binary_search(items, target):
    """Return the index of target in a sorted list, or -1."""
    lo, hi = 0, len(items) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if items[mid] == target:
            return mid
        if items[mid] < target:
            lo = mid + 1
        else:
            hi = mid - 1
    return -1
''',
         expected=['while lo < hi:']),

    dict(id="v3_float_equal", category="logic", kind="bug",
         code='''def order_total_matches(prices, expected_total):
    """True when the item prices add up to the expected total."""
    return sum(prices) == expected_total
''',
         expected=['return sum(prices) == expected_total']),

    dict(id="v3_missing_return", category="logic", kind="bug",
         code='''def next_port(value):
    def parse(v):
        if v.isdigit():
            return int(v)
    return parse(value) + 1
''',
         expected=['return parse(value) + 1']),

    dict(id="v3_precedence", category="logic", kind="bug",
         code='''def can_edit(user, document):
    """Admins and owners may edit a document unless it is locked."""
    return user.is_admin or user.is_owner and not document.locked
''',
         expected=['return user.is_admin or user.is_owner and not document.locked']),

    dict(id="v3_default_datetime", category="logic", kind="bug",
         code='''from datetime import datetime


def log_event(message, timestamp=datetime.now()):
    return {"message": message, "timestamp": timestamp}
''',
         expected=['def log_event(message, timestamp=datetime.now()):']),

    dict(id="v3_shallow_copy", category="logic", kind="bug",
         code='''def with_extra_path(settings, extra):
    """Return a copy of settings with one more search path; do not modify the original."""
    backup = settings.copy()
    backup["paths"].append(extra)
    return backup
''',
         expected=['backup["paths"].append(extra)']),

    dict(id="v3_missing_await", category="logic", kind="bug",
         code='''async def fetch_user(user_id):
    return {"id": user_id, "name": "demo"}


async def greet(user_id):
    user = fetch_user(user_id)
    return "Hello " + user["name"]
''',
         expected=['user = fetch_user(user_id)']),

    dict(id="v3_dict_default", category="logic", kind="bug",
         code='''def count_words(words):
    counts = {}
    for word in words:
        counts[word] = counts.get(word) + 1
    return counts
''',
         expected=['counts[word] = counts.get(word) + 1']),

    # ---------------- Clean files (safe lookalikes) ----------------
    dict(id="v3_clean_orderby", category="clean", kind="clean",
         code='''ALLOWED_SORT_COLUMNS = {"title", "created_at"}


def list_posts(cur, sort_by):
    column = sort_by if sort_by in ALLOWED_SORT_COLUMNS else "title"
    cur.execute(f"SELECT id, title FROM posts ORDER BY {column}")
    return cur.fetchall()
''', expected=[]),

    dict(id="v3_clean_tar", category="clean", kind="clean",
         code='''import subprocess


def backup(folder):
    archive = "backup.tgz"
    subprocess.run(["tar", "-czf", archive, "--", folder], check=True)
    return archive
''', expected=[]),

    dict(id="v3_clean_token", category="clean", kind="clean",
         code='''import secrets


def new_session_token():
    return secrets.token_urlsafe(32)
''', expected=[]),

    dict(id="v3_clean_xml", category="clean", kind="clean",
         code='''from defusedxml import ElementTree


def read_invoice(xml_text):
    root = ElementTree.fromstring(xml_text)
    return root.findtext("total")
''', expected=[]),

    dict(id="v3_clean_json", category="clean", kind="clean",
         code='''import json


def load_settings(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)
''', expected=[]),

    dict(id="v3_clean_binary_search", category="clean", kind="clean",
         code='''def binary_search(items, target):
    """Return the index of target in a sorted list, or -1."""
    lo, hi = 0, len(items) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if items[mid] == target:
            return mid
        if items[mid] < target:
            lo = mid + 1
        else:
            hi = mid - 1
    return -1
''', expected=[]),

    dict(id="v3_clean_decimal", category="clean", kind="clean",
         code='''from decimal import Decimal


def order_total_matches(prices, expected_total):
    total = sum((Decimal(str(p)) for p in prices), Decimal("0"))
    return total == Decimal(str(expected_total))
''', expected=[]),

    dict(id="v3_clean_precedence", category="clean", kind="clean",
         code='''def can_edit(user, document):
    """Admins and owners may edit a document unless it is locked."""
    return (user.is_admin or user.is_owner) and not document.locked
''', expected=[]),

    dict(id="v3_clean_datetime", category="clean", kind="clean",
         code='''from datetime import datetime, timezone


def log_event(message, timestamp=None):
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)
    return {"message": message, "timestamp": timestamp}
''', expected=[]),

    dict(id="v3_clean_deepcopy", category="clean", kind="clean",
         code='''import copy


def with_extra_path(settings, extra):
    backup = copy.deepcopy(settings)
    backup["paths"].append(extra)
    return backup
''', expected=[]),
]

"""
Labeled evaluation cases for PR Sentinel.

Each case is a small, self-contained Python file that is presented to the
pipeline as a brand-new file in a pull request.

- kind "bug":   `expected` lists the lines that contain a real defect. A line is
                identified by a substring that appears exactly once in `code`.
- kind "clean": no real defect; any security/logic finding is a false alarm.
"""

CASES = [
    # ---------------- Hardcoded secrets ----------------
    dict(id="secret_1", category="hardcoded_secret", kind="bug",
         code='''import requests

API_KEY = "abc123secretvalue"


def fetch(url):
    return requests.get(url, headers={"Authorization": API_KEY}, timeout=5)
''',
         expected=['API_KEY = "abc123secretvalue"']),

    dict(id="secret_2", category="hardcoded_secret", kind="bug",
         code='''def connect(open_conn):
    password = "hunter2"
    return open_conn("db.internal", "admin", password)
''',
         expected=['password = "hunter2"']),

    dict(id="secret_3", category="hardcoded_secret", kind="bug",
         code='''class Client:
    def __init__(self):
        self.token = "tok_live_8f3a9c21d7"

    def headers(self):
        return {"Authorization": "Bearer " + self.token}
''',
         expected=['self.token = "tok_live_8f3a9c21d7"']),

    # ---------------- SQL injection ----------------
    dict(id="sql_1", category="sql_injection", kind="bug",
         code='''def get_user(cur, name):
    query = f"SELECT * FROM users WHERE name = '{name}'"
    cur.execute(query)
    return cur.fetchone()
''',
         expected=['query = f"SELECT * FROM users']),

    dict(id="sql_2", category="sql_injection", kind="bug",
         code='''def delete_order(cur, order_id):
    cur.execute("DELETE FROM orders WHERE id = " + order_id)
''',
         expected=['cur.execute("DELETE FROM orders']),

    dict(id="sql_3", category="sql_injection", kind="bug",
         code='''def search(cur, term):
    sql = "SELECT * FROM items WHERE title LIKE '%{}%'".format(term)
    return cur.execute(sql).fetchall()
''',
         expected=['sql = "SELECT * FROM items']),

    # ---------------- Unsafe execution / deserialization ----------------
    dict(id="eval_1", category="unsafe_exec", kind="bug",
         code='''def calculate(expression):
    return eval(expression)
''',
         expected=['return eval(expression)']),

    dict(id="exec_1", category="unsafe_exec", kind="bug",
         code='''def run_plugin(code_text):
    namespace = {}
    exec(code_text, namespace)
    return namespace
''',
         expected=['exec(code_text, namespace)']),

    dict(id="pickle_1", category="unsafe_deserialization", kind="bug",
         code='''import pickle


def load_session(raw_bytes):
    return pickle.loads(raw_bytes)
''',
         expected=['pickle.loads(raw_bytes)']),

    dict(id="yaml_1", category="unsafe_deserialization", kind="bug",
         code='''import yaml


def read_config(text):
    return yaml.load(text, Loader=yaml.Loader)
''',
         expected=['yaml.load(text, Loader=yaml.Loader)']),

    # ---------------- Weak crypto ----------------
    dict(id="crypto_1", category="weak_crypto", kind="bug",
         code='''import hashlib


def hash_password(pw):
    return hashlib.md5(pw.encode()).hexdigest()
''',
         expected=['hashlib.md5(pw.encode())']),

    dict(id="crypto_2", category="weak_crypto", kind="bug",
         code='''import hashlib


def reset_token(user_id, secret):
    return hashlib.sha1((user_id + secret).encode()).hexdigest()
''',
         expected=['hashlib.sha1((user_id']),

    # ---------------- Path traversal (Bandit does not catch these) ----------------
    dict(id="path_1", category="path_traversal", kind="bug",
         code='''import os

BASE_DIR = "/srv/uploads"


def read_upload(filename):
    path = os.path.join(BASE_DIR, filename)
    with open(path) as f:
        return f.read()
''',
         expected=['path = os.path.join(BASE_DIR, filename)']),

    dict(id="path_2", category="path_traversal", kind="bug",
         code='''import os


def delete_report(report_name):
    os.remove("reports/" + report_name)
''',
         expected=['os.remove("reports/" + report_name)']),

    # ---------------- Logic bugs (static tools cannot catch these) ----------------
    dict(id="logic_1", category="logic", kind="bug",
         code='''def last_n(items, n):
    result = []
    for i in range(len(items) - n, len(items) + 1):
        result.append(items[i])
    return result
''',
         expected=['for i in range(len(items) - n, len(items) + 1):']),

    dict(id="logic_2", category="logic", kind="bug",
         code='''def can_vote(age):
    """Return True if the person is 18 or older."""
    if age < 18:
        return True
    return False
''',
         expected=['if age < 18:']),

    dict(id="logic_3", category="logic", kind="bug",
         code='''def add_tag(tag, tags=[]):
    tags.append(tag)
    return tags
''',
         expected=['def add_tag(tag, tags=[]):']),

    dict(id="logic_4", category="logic", kind="bug",
         code='''def average(values):
    total = sum(values)
    return total / len(values)
''',
         expected=['return total / len(values)']),

    dict(id="logic_5", category="logic", kind="bug",
         code='''import re


def first_word(text):
    match = re.search(r"\\w+", text)
    return match.group(0)
''',
         expected=['return match.group(0)']),

    dict(id="logic_6", category="logic", kind="bug",
         code='''def apply_discount(price, percent):
    """percent is given as a number from 0 to 100."""
    return price - price * percent
''',
         expected=['return price - price * percent']),

    # ---------------- Clean code (should produce no real findings) ----------------
    dict(id="clean_1", category="clean", kind="clean",
         code='''def get_user(cur, name):
    cur.execute("SELECT * FROM users WHERE name = %s", (name,))
    return cur.fetchone()
''', expected=[]),

    dict(id="clean_2", category="clean", kind="clean",
         code='''import os

import requests


def fetch(url):
    api_key = os.environ["API_KEY"]
    return requests.get(url, headers={"Authorization": api_key}, timeout=5)
''', expected=[]),

    dict(id="clean_3", category="clean", kind="clean",
         code='''import yaml


def read_config(text):
    return yaml.safe_load(text)
''', expected=[]),

    dict(id="clean_4", category="clean", kind="clean",
         code='''import hashlib


def checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
''', expected=[]),

    dict(id="clean_5", category="clean", kind="clean",
         code='''from pathlib import Path

BASE_DIR = Path("/srv/uploads").resolve()


def read_upload(filename):
    path = (BASE_DIR / filename).resolve()
    if BASE_DIR not in path.parents:
        raise ValueError("invalid path")
    return path.read_text(encoding="utf-8")
''', expected=[]),

    dict(id="clean_6", category="clean", kind="clean",
         code='''def average(values):
    if not values:
        return 0.0
    return sum(values) / len(values)
''', expected=[]),

    dict(id="clean_7", category="clean", kind="clean",
         code='''def add_tag(tag, tags=None):
    if tags is None:
        tags = []
    tags.append(tag)
    return tags
''', expected=[]),

    dict(id="clean_8", category="clean", kind="clean",
         code='''from dataclasses import dataclass


@dataclass
class Point:
    x: float
    y: float

    def distance_to(self, other):
        return ((self.x - other.x) ** 2 + (self.y - other.y) ** 2) ** 0.5
''', expected=[]),

    dict(id="clean_9", category="clean", kind="clean",
         code='''def apply_discount(price, percent):
    """percent is given as a number from 0 to 100."""
    return price - price * percent / 100
''', expected=[]),

    dict(id="clean_10", category="clean", kind="clean",
         code='''def last_n(items, n):
    if n <= 0:
        return []
    return items[-n:]
''', expected=[]),
]

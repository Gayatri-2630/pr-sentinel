"""
Posts findings as inline review comments on the exact changed line, the way
a human reviewer would, in addition to the single summary comment.

To keep a PR readable this is selective:
- only verified findings of medium severity or higher,
- only on lines that are part of the diff (GitHub rejects anything else),
- duplicates from several tools are merged first,
- at most MAX_INLINE_COMMENTS per run, most severe first,
- a hidden marker per (file, line) stops the same comment being posted again
  when new commits are pushed to the PR.
Everything else still appears in the summary comment.
"""

import hashlib

import requests

from app.diff_utils import commentable_lines
from app.findings_merge import merge_duplicate_findings
from app.github_auth import get_installation_token

REQUEST_TIMEOUT_SECONDS = 10
MAX_INLINE_COMMENTS = 8
MAX_MESSAGE_CHARS = 500
MARKER_PREFIX = "<!-- pr-sentinel-inline:"
MARKER_SUFFIX = " -->"
REVIEW_BODY = "PR Sentinel left inline comments. The summary comment has the full list."

SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2}   # lower = more severe
SOURCE_LABELS = {
    "security": "Security agent",
    "logic": "Logic agent",
    "style": "Style agent",
    "static_analysis_bandit": "Bandit",
    "static_analysis_pylint": "Pylint",
}


def _clean(text, limit=MAX_MESSAGE_CHARS) -> str:
    """Finding text is untrusted: escape HTML and defuse @mentions."""
    text = str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = text.replace("@", "@​")
    if len(text) > limit:
        text = text[: limit - 3] + "..."
    return text


def _key(path: str, line: int) -> str:
    return hashlib.sha1(f"{path}:{line}".encode("utf-8")).hexdigest()[:12]


def _normalize_path(path) -> str:
    path = str(path or "")
    return path[2:] if path.startswith("./") else path


def build_inline_comments(findings: list[dict], diff_text: str) -> list[dict]:
    """Choose which findings become inline comments. Pure function (no network)."""
    commentable = commentable_lines(diff_text)

    candidates = []
    for finding in merge_duplicate_findings(findings):
        if not finding.get("verified"):
            continue
        severity = str(finding.get("severity", "")).lower()
        if severity not in SEVERITY_RANK:
            continue
        path = _normalize_path(finding.get("file_path"))
        line = finding.get("line_number")
        if isinstance(line, bool) or not isinstance(line, int):
            continue
        if line not in commentable.get(path, set()):
            continue
        candidates.append((SEVERITY_RANK[severity], severity, finding, path, line))

    candidates.sort(key=lambda item: item[0])   # stable: keeps original order within a severity

    comments = []
    seen = set()
    for _, severity, finding, path, line in candidates:
        key = _key(path, line)
        if key in seen:
            continue
        seen.add(key)
        names = [SOURCE_LABELS.get(finding.get("agent_type"), str(finding.get("agent_type", "unknown")))]
        names += [SOURCE_LABELS.get(n, n) for n in finding.get("also_reported_by", [])]
        body = (
            f"{MARKER_PREFIX}{key}{MARKER_SUFFIX}\n"
            f"**{severity.capitalize()}** - {', '.join(names)}\n\n"
            f"{_clean(finding.get('message', ''))}"
        )
        comments.append({"path": path, "line": line, "side": "RIGHT", "body": body, "key": key})
        if len(comments) >= MAX_INLINE_COMMENTS:
            break
    return comments


def _existing_keys(base: str, headers: dict, pr_number: int) -> set[str]:
    """Markers of inline comments we already posted on this PR."""
    keys = set()
    for page in range(1, 4):
        response = requests.get(
            f"{base}/pulls/{int(pr_number)}/comments",
            headers=headers,
            params={"per_page": 100, "page": page},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        items = response.json()
        for item in items:
            body = item.get("body", "")
            if item.get("user", {}).get("type") != "Bot" or MARKER_PREFIX not in body:
                continue
            start = body.index(MARKER_PREFIX) + len(MARKER_PREFIX)
            end = body.find(MARKER_SUFFIX, start)
            if end != -1:
                keys.add(body[start:end])
        if len(items) < 100:
            break
    return keys


def post_inline_comments(
    installation_id,
    repo_full_name: str,
    pr_number: int,
    head_sha: str,
    diff_text: str,
    findings: list[dict],
) -> int:
    """Post new inline comments. Returns how many were posted."""
    comments = build_inline_comments(findings, diff_text)
    if not comments:
        return 0

    token = get_installation_token(installation_id)
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }
    base = f"https://api.github.com/repos/{repo_full_name}"

    already_posted = _existing_keys(base, headers, pr_number)
    fresh = [c for c in comments if c["key"] not in already_posted]
    if not fresh:
        return 0
    payload = [{k: c[k] for k in ("path", "line", "side", "body")} for c in fresh]

    response = requests.post(
        f"{base}/pulls/{int(pr_number)}/reviews",
        headers=headers,
        json={"commit_id": head_sha, "event": "COMMENT", "body": REVIEW_BODY, "comments": payload},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code == 422:
        # One comment was rejected, which fails the whole batch. Post them one
        # by one so a single bad line cannot block the others.
        posted = 0
        for comment in payload:
            single = requests.post(
                f"{base}/pulls/{int(pr_number)}/comments",
                headers=headers,
                json={"commit_id": head_sha, **comment},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            if single.status_code < 300:
                posted += 1
        return posted

    response.raise_for_status()
    return len(payload)
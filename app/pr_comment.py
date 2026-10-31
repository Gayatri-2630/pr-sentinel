"""
Posts PR Sentinel's results back to the pull request as ONE summary comment
that is updated in place on every push (found by a hidden marker), so a PR
never fills up with a new comment per commit.

Finding text comes from LLM output and from the code under review, so it is
untrusted. Before it goes into GitHub markdown it is sanitized: @mentions
are defused (no pinging strangers), HTML is escaped, and table-breaking
characters are neutralized.

Findings that several tools report for the same problem are merged for
display only. The database keeps every raw finding, so per-agent statistics
on the dashboard stay accurate.
"""

import requests

from app.findings_merge import merge_duplicate_findings
from app.github_auth import get_installation_token

COMMENT_MARKER = "<!-- pr-sentinel-review -->"
REQUEST_TIMEOUT_SECONDS = 10
MAX_ROWS = 25
MAX_MESSAGE_CHARS = 300
MAX_COMMENT_CHARS = 60000  # GitHub's hard limit is 65536

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
SOURCE_LABELS = {
    "security": "Security agent",
    "logic": "Logic agent",
    "style": "Style agent",
    "static_analysis_bandit": "Bandit",
    "static_analysis_pylint": "Pylint",
}


def _sanitize(text, limit=MAX_MESSAGE_CHARS) -> str:
    text = str(text).replace("\r", " ").replace("\n", " ")
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = text.replace("@", "@​")  # defuse @mentions
    text = text.replace("|", "\\|")      # keep table cells intact
    if len(text) > limit:
        text = text[: limit - 3] + "..."
    return text


def _row(finding: dict) -> str:
    source = SOURCE_LABELS.get(finding.get("agent_type"), finding.get("agent_type", "unknown"))
    extra = [SOURCE_LABELS.get(name, name) for name in finding.get("also_reported_by", [])]
    if extra:
        source = f"{source} + {', '.join(extra)}"
    line = finding.get("line_number")
    location = f"{_sanitize(finding.get('file_path', 'unknown'), 120)}" + (f":{line}" if line else "")
    return (
        f"| {_sanitize(finding.get('severity', 'low'), 12)} | {_sanitize(source, 60)} "
        f"| `{location.replace('`', '')}` | {_sanitize(finding.get('message', ''))} |"
    )


def _sorted(findings: list[dict]) -> list[dict]:
    return sorted(findings, key=lambda f: SEVERITY_ORDER.get(f.get("severity"), 9))


def _table(findings: list[dict]) -> str:
    lines = ["| Severity | Source | Location | Finding |", "|---|---|---|---|"]
    lines.extend(_row(f) for f in _sorted(findings)[:MAX_ROWS])
    if len(findings) > MAX_ROWS:
        lines.append(f"| | | | ...and {len(findings) - MAX_ROWS} more |")
    return "\n".join(lines)


def build_comment_body(review_id: int, findings: list[dict], ai_status: dict) -> str:
    """Verified AI findings and all static findings are shown up front.
    AI findings the verifier could not confirm are collapsed, not hidden."""
    findings = merge_duplicate_findings(findings)
    trusted = [f for f in findings if f.get("verified")]
    unverified = [f for f in findings if not f.get("verified")]

    parts = [COMMENT_MARKER, "## PR Sentinel review", ""]

    if trusted:
        serious = sum(1 for f in trusted if f.get("severity") in ("critical", "high"))
        parts.append(f"**{len(trusted)} finding(s)** in the files changed by this PR ({serious} high or critical).")
        parts += ["", _table(trusted)]
    else:
        parts.append("No confirmed findings in the files changed by this PR.")

    if unverified:
        parts += [
            "",
            "<details>",
            f"<summary>{len(unverified)} AI finding(s) could not be verified</summary>",
            "",
            _table(unverified),
            "",
            "</details>",
        ]

    degraded = {name: status for name, status in ai_status.items() if status != "ok"}
    if degraded:
        detail = ", ".join(f"{name} ({status})" for name, status in degraded.items())
        parts += [
            "",
            f"Note: AI analysis was incomplete: {detail}. "
            "Static analysis (Bandit, Pylint) results above are complete.",
        ]

    parts += ["", f"<sub>Review #{review_id}. Generated automatically and can contain mistakes.</sub>"]
    body = "\n".join(parts)
    return body[:MAX_COMMENT_CHARS]


def post_review_comment(
    installation_id,
    repo_full_name: str,
    pr_number: int,
    review_id: int,
    findings: list[dict],
    ai_status: dict,
) -> None:
    """Create the summary comment, or update the one we posted earlier."""
    token = get_installation_token(installation_id)
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }
    base = f"https://api.github.com/repos/{repo_full_name}"
    body = build_comment_body(review_id, findings, ai_status)

    existing_id = None
    for page in range(1, 4):  # look through up to 300 comments
        response = requests.get(
            f"{base}/issues/{int(pr_number)}/comments",
            headers=headers,
            params={"per_page": 100, "page": page},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        comments = response.json()
        for comment in comments:
            if COMMENT_MARKER in comment.get("body", "") and comment.get("user", {}).get("type") == "Bot":
                existing_id = comment["id"]
                break
        if existing_id or len(comments) < 100:
            break

    if existing_id:
        response = requests.patch(
            f"{base}/issues/comments/{existing_id}",
            headers=headers, json={"body": body}, timeout=REQUEST_TIMEOUT_SECONDS,
        )
    else:
        response = requests.post(
            f"{base}/issues/{int(pr_number)}/comments",
            headers=headers, json={"body": body}, timeout=REQUEST_TIMEOUT_SECONDS,
        )
    response.raise_for_status()
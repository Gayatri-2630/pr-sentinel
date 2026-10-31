from app import pr_comment
from app.pr_comment import COMMENT_MARKER, build_comment_body, post_review_comment


def make(agent="security", severity="high", line=3, message="Something wrong", verified=True,
         file_path="app/x.py"):
    return {"agent_type": agent, "severity": severity, "file_path": file_path,
            "line_number": line, "message": message, "verified": verified}


OK = {"security": "ok", "logic": "ok", "style": "ok"}


# ---------- build_comment_body ----------

def test_comment_starts_with_the_hidden_marker():
    assert build_comment_body(1, [], OK).startswith(COMMENT_MARKER)


def test_no_findings_message():
    body = build_comment_body(1, [], OK)
    assert "No confirmed findings" in body


def test_duplicate_findings_appear_once_with_all_sources():
    findings = [
        make("security", "high", 2, "Hardcoded credential in 'password'"),
        make("static_analysis_bandit", "low", 2, "[B105] Possible hardcoded password"),
        make("style", "medium", 2, "Hardcoded secret or password in source"),
    ]
    body = build_comment_body(1, findings, OK)
    assert "**1 finding(s)**" in body
    assert "Security agent + Bandit, Style agent" in body


def test_unverified_findings_are_collapsed_not_hidden():
    body = build_comment_body(1, [make(verified=False)], OK)
    assert "<details>" in body
    assert "1 AI finding(s) could not be verified" in body
    assert "No confirmed findings" in body


def test_untrusted_text_is_sanitized():
    nasty = make(message="<script>alert(1)</script> @octocat a | b\nnext line")
    body = build_comment_body(1, [nasty], OK)
    assert "<script>" not in body
    assert "&lt;script&gt;" in body
    assert "@octocat" not in body          # a zero-width space now follows the @
    assert "a \\| b" in body               # pipe escaped so the table survives
    assert "b next line" in body           # newline flattened


def test_long_lists_are_capped():
    findings = [make(message=f"Issue number {i}", line=i + 1) for i in range(30)]
    body = build_comment_body(1, findings, OK)
    assert "...and 5 more" in body


def test_most_severe_findings_come_first():
    findings = [
        make(severity="low", line=1, message="Minor thing"),
        make(severity="critical", line=2, message="Big thing"),
    ]
    body = build_comment_body(1, findings, OK)
    assert body.index("Big thing") < body.index("Minor thing")


def test_degraded_ai_is_reported():
    body = build_comment_body(1, [], {"security": "quota_exhausted", "logic": "ok"})
    assert "AI analysis was incomplete: security (quota_exhausted)" in body


# ---------- post_review_comment (GitHub API calls are faked) ----------

class FakeResponse:
    def __init__(self, data=None):
        self._data = data if data is not None else []

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def install_fake_github(monkeypatch, existing_comments):
    calls = []
    monkeypatch.setattr(pr_comment, "get_installation_token", lambda _installation: "fake-token")
    monkeypatch.setattr(pr_comment.requests, "get",
                        lambda url, **kw: FakeResponse(existing_comments))
    monkeypatch.setattr(pr_comment.requests, "post",
                        lambda url, **kw: calls.append(("post", url)) or FakeResponse())
    monkeypatch.setattr(pr_comment.requests, "patch",
                        lambda url, **kw: calls.append(("patch", url)) or FakeResponse())
    return calls


def test_creates_a_new_comment_when_none_exists(monkeypatch):
    calls = install_fake_github(monkeypatch, existing_comments=[])
    post_review_comment(1, "owner/repo", 7, 1, [], OK)
    assert [c[0] for c in calls] == ["post"]
    assert calls[0][1].endswith("/repos/owner/repo/issues/7/comments")


def test_updates_the_existing_comment_in_place(monkeypatch):
    existing = [{"id": 77, "body": COMMENT_MARKER + " old review", "user": {"type": "Bot"}}]
    calls = install_fake_github(monkeypatch, existing_comments=existing)
    post_review_comment(1, "owner/repo", 7, 2, [], OK)
    assert [c[0] for c in calls] == ["patch"]
    assert calls[0][1].endswith("/issues/comments/77")


def test_a_human_pasting_our_marker_is_not_treated_as_our_comment(monkeypatch):
    existing = [{"id": 5, "body": COMMENT_MARKER, "user": {"type": "User"}}]
    calls = install_fake_github(monkeypatch, existing_comments=existing)
    post_review_comment(1, "owner/repo", 7, 3, [], OK)
    assert [c[0] for c in calls] == ["post"]
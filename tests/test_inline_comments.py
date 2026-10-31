from app import inline_comments
from app.inline_comments import (
    MARKER_PREFIX,
    MAX_INLINE_COMMENTS,
    build_inline_comments,
    post_inline_comments,
)

DIFF = "\n".join([
    "diff --git a/app/x.py b/app/x.py",
    "--- a/app/x.py",
    "+++ b/app/x.py",
    "@@ -1,2 +1,12 @@",
] + ["+line"] * 12)   # new lines 1..12 are all in the diff


def make(agent="security", severity="high", line=3, message="Hardcoded password",
         verified=True, file_path="app/x.py"):
    return {"agent_type": agent, "severity": severity, "file_path": file_path,
            "line_number": line, "message": message, "verified": verified}


# ---------- choosing which findings become inline comments ----------

def test_verified_serious_finding_on_a_diff_line_is_selected():
    comments = build_inline_comments([make()], DIFF)
    assert len(comments) == 1
    assert (comments[0]["path"], comments[0]["line"], comments[0]["side"]) == ("app/x.py", 3, "RIGHT")
    assert MARKER_PREFIX in comments[0]["body"]


def test_unverified_findings_are_skipped():
    assert build_inline_comments([make(verified=False)], DIFF) == []


def test_low_severity_is_skipped():
    assert build_inline_comments([make(severity="low")], DIFF) == []


def test_lines_outside_the_diff_are_skipped():
    assert build_inline_comments([make(line=99)], DIFF) == []


def test_files_outside_the_diff_are_skipped():
    assert build_inline_comments([make(file_path="other.py")], DIFF) == []


def test_leading_dot_slash_in_path_is_ignored():
    assert len(build_inline_comments([make(file_path="./app/x.py")], DIFF)) == 1


def test_duplicates_from_several_tools_become_one_comment():
    findings = [
        make("security", "high", 3, "Hardcoded credential in 'password'"),
        make("static_analysis_bandit", "medium", 3, "[B105] Possible hardcoded password"),
    ]
    comments = build_inline_comments(findings, DIFF)
    assert len(comments) == 1
    assert "Security agent, Bandit" in comments[0]["body"]


def test_most_severe_first_and_capped():
    findings = [make(severity="medium", line=i, message=f"Medium issue {i}") for i in range(1, 11)]
    findings.append(make(severity="critical", line=11, message="Critical issue"))
    comments = build_inline_comments(findings, DIFF)
    assert len(comments) == MAX_INLINE_COMMENTS
    assert "Critical issue" in comments[0]["body"]


def test_untrusted_text_is_escaped():
    comments = build_inline_comments([make(message="<img src=x> @octocat")], DIFF)
    assert "<img" not in comments[0]["body"]
    assert "@octocat" not in comments[0]["body"]


# ---------- posting (GitHub API is faked) ----------

class FakeResponse:
    def __init__(self, data=None, status_code=200):
        self._data = data if data is not None else []
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._data


def install_fake_github(monkeypatch, existing=None, batch_status=200):
    calls = []
    monkeypatch.setattr(inline_comments, "get_installation_token", lambda _i: "fake-token")
    monkeypatch.setattr(inline_comments.requests, "get",
                        lambda url, **kw: FakeResponse(existing or []))

    def fake_post(url, **kw):
        calls.append((url, kw["json"]))
        if url.endswith("/reviews"):
            return FakeResponse(status_code=batch_status)
        return FakeResponse(status_code=201)

    monkeypatch.setattr(inline_comments.requests, "post", fake_post)
    return calls


def post(findings):
    return post_inline_comments(1, "owner/repo", 7, "abc123", DIFF, findings)


def test_posts_one_review_with_the_comments(monkeypatch):
    calls = install_fake_github(monkeypatch)
    assert post([make(line=3), make(line=5, message="Another problem")]) == 2
    assert len(calls) == 1
    url, payload = calls[0]
    assert url.endswith("/pulls/7/reviews")
    assert payload["commit_id"] == "abc123"
    assert payload["event"] == "COMMENT"
    assert len(payload["comments"]) == 2
    assert set(payload["comments"][0]) == {"path", "line", "side", "body"}


def test_nothing_is_posted_when_nothing_qualifies(monkeypatch):
    calls = install_fake_github(monkeypatch)
    assert post([make(severity="low")]) == 0
    assert calls == []


def test_comments_already_posted_are_not_repeated(monkeypatch):
    first = build_inline_comments([make(line=3)], DIFF)[0]
    existing = [{"body": first["body"], "user": {"type": "Bot"}}]
    calls = install_fake_github(monkeypatch, existing=existing)
    assert post([make(line=3)]) == 0
    assert calls == []


def test_a_human_copying_our_marker_does_not_suppress_comments(monkeypatch):
    first = build_inline_comments([make(line=3)], DIFF)[0]
    existing = [{"body": first["body"], "user": {"type": "User"}}]
    install_fake_github(monkeypatch, existing=existing)
    assert post([make(line=3)]) == 1


def test_falls_back_to_single_comments_if_github_rejects_the_batch(monkeypatch):
    calls = install_fake_github(monkeypatch, batch_status=422)
    assert post([make(line=3), make(line=5, message="Another problem")]) == 2
    urls = [c[0] for c in calls]
    assert urls[0].endswith("/reviews")
    assert all(u.endswith("/pulls/7/comments") for u in urls[1:])
    assert len(urls) == 3
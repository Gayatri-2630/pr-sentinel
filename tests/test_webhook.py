import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from app import main

SECRET = "test-webhook-secret"


def sign(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


def pr_payload(action="opened"):
    return {
        "action": action,
        "pull_request": {"number": 42, "head": {"sha": "abcdef1234567890"}},
        "repository": {
            "full_name": "someone/some-repo",
            "owner": {"login": "someone"},
            "default_branch": "main",
            "clone_url": "https://github.com/someone/some-repo.git",
        },
        "installation": {"id": 123456},
    }


@pytest.fixture
def client(monkeypatch):
    """A test client whose background job is replaced by a recorder, so no
    real review (network, Gemini, git) ever runs."""
    started = []
    monkeypatch.setattr(main, "process_pr_event", lambda **kwargs: started.append(kwargs))
    test_client = TestClient(main.app)
    test_client.started = started
    return test_client


def post_event(client, payload, event="pull_request", signature=None):
    body = json.dumps(payload).encode()
    headers = {"X-GitHub-Event": event, "Content-Type": "application/json"}
    headers["X-Hub-Signature-256"] = sign(body) if signature is None else signature
    return client.post("/webhook", content=body, headers=headers)


def test_health_endpoint(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_wrong_signature_is_rejected(client):
    response = post_event(client, pr_payload(), signature="sha256=" + "0" * 64)
    assert response.status_code == 401
    assert client.started == []


def test_missing_signature_header_is_rejected(client):
    body = json.dumps(pr_payload()).encode()
    response = client.post("/webhook", content=body,
                           headers={"X-GitHub-Event": "pull_request"})
    assert response.status_code == 401
    assert client.started == []


def test_tampered_body_is_rejected(client):
    original = json.dumps(pr_payload()).encode()
    tampered = original.replace(b"someone/some-repo", b"attacker/evil-repo")
    response = client.post("/webhook", content=tampered, headers={
        "X-GitHub-Event": "pull_request",
        "X-Hub-Signature-256": sign(original),
    })
    assert response.status_code == 401
    assert client.started == []


def test_non_pull_request_events_are_ignored(client):
    response = post_event(client, {"zen": "hello"}, event="ping")
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
    assert client.started == []


def test_closed_pull_requests_are_ignored(client):
    response = post_event(client, pr_payload(action="closed"))
    assert response.json()["status"] == "ignored"
    assert client.started == []


def test_opened_pull_request_is_queued(client):
    response = post_event(client, pr_payload())
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "queued"
    assert data["pr_number"] == 42
    assert len(client.started) == 1
    job = client.started[0]
    assert job["repo_full_name"] == "someone/some-repo"
    assert job["pr_number"] == 42
    assert job["head_sha"] == "abcdef1234567890"
    assert job["review_id"] == data["review_id"]
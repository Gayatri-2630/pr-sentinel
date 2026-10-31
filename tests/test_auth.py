from fastapi.testclient import TestClient

from app import main

TOKEN = "test-dashboard-token"
client = TestClient(main.app)


def bearer(value):
    return {"Authorization": f"Bearer {value}"}


def test_health_stays_public():
    assert client.get("/health").status_code == 200


def test_review_status_requires_a_token():
    assert client.get("/reviews/999999").status_code == 401


def test_dashboard_data_requires_a_token():
    assert client.get("/dashboard/data").status_code == 401


def test_wrong_token_is_rejected():
    assert client.get("/reviews/999999", headers=bearer("wrong")).status_code == 401


def test_token_in_the_url_is_not_accepted():
    # Tokens in URLs end up in server logs, so only the header is allowed.
    assert client.get(f"/reviews/999999?token={TOKEN}").status_code == 401


def test_correct_token_gets_through_to_the_endpoint():
    # 404 means authentication passed and the review simply does not exist.
    assert client.get("/reviews/999999", headers=bearer(TOKEN)).status_code == 404


def test_everything_is_denied_if_no_token_is_configured(monkeypatch):
    monkeypatch.setattr(main, "DASHBOARD_TOKEN", None)
    assert client.get("/reviews/999999", headers=bearer(TOKEN)).status_code == 503
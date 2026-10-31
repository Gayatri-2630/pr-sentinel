import pytest

from app.agents import orchestrator
from app.llm_client import LLMQuotaExhaustedError


def good(file_path="app/x.py", line=3, severity="high", message="Problem"):
    return {"file_path": file_path, "line_number": line, "severity": severity, "message": message}


@pytest.fixture
def stub_agents(monkeypatch):
    """Replace the three AI agents and the verifier with controllable fakes."""

    def install(security=None, logic=None, style=None, verifier=None):
        def runner(result):
            def run(_diff):
                if isinstance(result, Exception):
                    raise result
                return result if result is not None else []
            return run

        monkeypatch.setattr(orchestrator, "run_security_agent", runner(security))
        monkeypatch.setattr(orchestrator, "run_logic_agent", runner(logic))
        monkeypatch.setattr(orchestrator, "run_style_agent", runner(style))
        monkeypatch.setattr(
            orchestrator,
            "verify_all_findings",
            verifier or (lambda _diff, findings: findings),
        )

    return install


def test_valid_findings_are_tagged_with_their_agent(stub_agents):
    stub_agents(security=[good()], logic=[good(line=9)])
    findings, status = orchestrator.run_all_agents("diff")
    assert status == {"security": "ok", "logic": "ok", "style": "ok"}
    assert {f["agent_type"] for f in findings} == {"security", "logic"}


def test_malformed_findings_are_dropped_without_crashing(stub_agents):
    bad = [
        "just a string",
        {"file_path": "a.py", "severity": "low", "message": "no line number"},
        {"file_path": "a.py", "line_number": "abc", "severity": "low", "message": "bad line"},
        good(),
    ]
    stub_agents(security=bad)
    findings, status = orchestrator.run_all_agents("diff")
    assert status["security"] == "ok"
    assert len(findings) == 1


def test_line_number_is_converted_to_int(stub_agents):
    stub_agents(logic=[good(line="12")])
    findings, _ = orchestrator.run_all_agents("diff")
    assert findings[0]["line_number"] == 12


def test_quota_error_is_reported_and_other_agents_still_run(stub_agents):
    stub_agents(security=LLMQuotaExhaustedError("out of quota"), logic=[good()])
    findings, status = orchestrator.run_all_agents("diff")
    assert status["security"] == "quota_exhausted"
    assert status["logic"] == "ok"
    assert len(findings) == 1


def test_unexpected_error_is_reported_as_error(stub_agents):
    stub_agents(style=RuntimeError("server disconnected"), security=[good()])
    findings, status = orchestrator.run_all_agents("diff")
    assert status["style"] == "error"
    assert len(findings) == 1


def test_verifier_is_skipped_when_agents_found_nothing(stub_agents):
    def must_not_run(_diff, _findings):
        raise AssertionError("verifier should not be called")

    stub_agents(verifier=must_not_run)
    findings, status = orchestrator.run_all_agents("diff")
    assert findings == []
    assert status == {"security": "ok", "logic": "ok", "style": "ok"}


def test_static_findings_are_marked_verified_and_returned(stub_agents, monkeypatch):
    stub_agents()
    static = {"file_path": "a.py", "line_number": 1, "severity": "low",
              "message": "[B105] hardcoded", "agent_type": "static_analysis_bandit"}
    monkeypatch.setattr(orchestrator, "_run_static_analysis", lambda _d, _p: [dict(static)])
    findings, _ = orchestrator.run_all_agents("diff", repo_path="somewhere")
    assert len(findings) == 1
    assert findings[0]["verified"] is True
    assert "static analysis" in findings[0]["verification_reason"].lower()


def test_static_analysis_crash_does_not_lose_ai_findings(stub_agents, monkeypatch):
    stub_agents(security=[good()])

    def boom(_d, _p):
        raise RuntimeError("bandit exploded")

    monkeypatch.setattr(orchestrator, "_run_static_analysis", boom)
    findings, status = orchestrator.run_all_agents("diff", repo_path="somewhere")
    assert status["security"] == "ok"
    assert len(findings) == 1
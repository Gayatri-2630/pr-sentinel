"""
Orchestrator for PR Sentinel's analysis layer.

Runs the Security, Logic and Style AI agents on the diff, while Bandit and
Pylint scan the PR's changed Python files at the same time in a background
thread (static analysis is CPU/subprocess work, the agents are network
waits, so they overlap well). Only AI findings go through the LLM
verification pass; static analysis tools are rule-based and don't
hallucinate, so verifying them would waste API quota.

AI availability is tracked explicitly: if the LLM provider is down or out
of quota, that is reported as a status, and static analysis still delivers.
"""

import time
from concurrent.futures import ThreadPoolExecutor

from app.agents.logic_agent import run_logic_agent
from app.agents.security_agent import run_security_agent
from app.agents.style_agent import run_style_agent
from app.agents.verifier import verify_all_findings
from app.llm_client import LLMQuotaExhaustedError
from app.static_analysis import extract_changed_python_files, run_bandit, run_pylint


def _run_static_analysis(diff_text: str, repo_path: str) -> list[dict]:
    """Bandit then Pylint on the PR's changed files, one at a time so two
    subprocesses never compete for a small instance's memory."""
    started = time.perf_counter()
    changed_files = extract_changed_python_files(diff_text)
    print(f"Static analysis scope: {len(changed_files)} changed Python file(s).")

    findings = []
    if changed_files:
        for tool_name, tool_function in [("bandit", run_bandit), ("pylint", run_pylint)]:
            try:
                findings.extend(tool_function(repo_path, changed_files))
            except Exception as e:  # pylint: disable=broad-exception-caught
                print(f"{tool_name} failed with an error: {e}")

    print(f"Static analysis finished in {time.perf_counter() - started:.1f}s.")
    return findings


def run_all_agents(diff_text: str, repo_path: str = None) -> tuple[list[dict], dict]:
    """
    Returns (findings, ai_status), where ai_status looks like
    {"security": "ok", "logic": "quota_exhausted", "style": "error"}.
    """
    agent_runs = [
        ("security", run_security_agent),
        ("logic", run_logic_agent),
        ("style", run_style_agent),
    ]

    ai_findings = []
    ai_status = {}

    with ThreadPoolExecutor(max_workers=1) as executor:
        static_future = (
            executor.submit(_run_static_analysis, diff_text, repo_path) if repo_path else None
        )

        # The agents stay sequential on purpose: the free Gemini tier allows
        # only a few requests per minute, so parallel calls would just hit 429s.
        ai_started = time.perf_counter()
        for agent_type, agent_function in agent_runs:
            try:
                findings = agent_function(diff_text)
                ai_status[agent_type] = "ok"
            except LLMQuotaExhaustedError as e:
                print(f"{agent_type} agent unavailable -- Gemini quota exhausted: {e}")
                ai_status[agent_type] = "quota_exhausted"
                findings = []
            except Exception as e:  # pylint: disable=broad-exception-caught
                print(f"{agent_type} agent failed with an error: {e}")
                ai_status[agent_type] = "error"
                findings = []

            valid_findings = []
            for finding in findings:
                if not isinstance(finding, dict):
                    continue
                if not {"file_path", "line_number", "severity", "message"} <= finding.keys():
                    continue
                try:
                    finding["line_number"] = int(finding["line_number"])
                except (TypeError, ValueError):
                    continue
                finding["agent_type"] = agent_type
                valid_findings.append(finding)
            dropped = len(findings) - len(valid_findings)
            if dropped:
                print(f"{agent_type} agent: dropped {dropped} malformed finding(s).")
            ai_findings.extend(valid_findings)

        # No point calling the verifier if no AI agent produced anything.
        if ai_findings:
            ai_findings = verify_all_findings(diff_text, ai_findings)
        print(f"AI agents + verification finished in {time.perf_counter() - ai_started:.1f}s.")

        static_findings = []
        if static_future is not None:
            try:
                static_findings = static_future.result()
            except Exception as e:  # pylint: disable=broad-exception-caught
                print(f"Static analysis thread failed: {e}")

    for finding in static_findings:
        finding["verified"] = True
        finding["verification_reason"] = "Deterministic static analysis tool -- not run through LLM verification."

    return ai_findings + static_findings, ai_status
"""
Runs real, deterministic static analysis tools (bandit, pylint) against a
cloned repo, and converts their output into the same finding-dict shape
our AI agents use -- so everything flows through the same save/display
pipeline regardless of whether an LLM or a fixed-rule tool produced it.
"""
 
import json
import os
import subprocess
 
BANDIT_SEVERITY_MAP = {
    "LOW": "low",
    "MEDIUM": "medium",
    "HIGH": "high",
}
 
PYLINT_SEVERITY_MAP = {
    "fatal": "critical",
    "error": "high",
    "warning": "medium",
    "convention": "low",
    "refactor": "low",
}
 
 
def run_bandit(repo_path: str) -> list[dict]:
    """
    Run bandit against a cloned repo's code and return findings in our
    standard dict shape. Fails safe -- returns [] rather than crashing
    the pipeline if anything goes wrong.
    """
    target_path = os.path.join(repo_path, "app")
    if not os.path.exists(target_path):
        target_path = repo_path
 
    try:
        # check=False: bandit's own exit code is non-zero when it FINDS
        # issues -- that's expected, not a failure, so we don't want
        # subprocess to raise on that. Fixed, hardcoded command list
        # (no user input reaches this call), so injection risk is not
        # applicable here despite what a generic linter rule assumes.
        result = subprocess.run(
            ["bandit", "-r", target_path, "-f", "json"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        data = json.loads(result.stdout) if result.stdout.strip() else {}
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError) as e:
        print(f"Bandit run failed, skipping: {e}")
        return [{
            "agent_type": "static_analysis_bandit",
            "file_path": target_path,
            "line_number": None,
            "severity": "low",
            "message": f"Bandit could not complete: {e}",
        }]
 
    findings = []
    for issue in data.get("results", []):
        findings.append({
            "agent_type": "static_analysis_bandit",
            "file_path": issue.get("filename", "unknown"),
            "line_number": issue.get("line_number"),
            "severity": BANDIT_SEVERITY_MAP.get(issue.get("issue_severity", "LOW"), "low"),
            "message": f"[{issue.get('test_id')}] {issue.get('issue_text', '')}",
        })
 
    return findings
 
 
def run_pylint(repo_path: str) -> list[dict]:
    """
    Run pylint against a cloned repo's code and return findings in our
    standard dict shape.
 
    Important flags, and why:
    - --disable=import-error: pylint otherwise tries to IMPORT the code it
      analyzes, which loads heavy deps (torch, sentence-transformers, faiss)
      and caused multi-minute hangs on Windows. We only want static text
      analysis here, not runtime imports.
    - no --jobs: parallel mode has a known hang issue on Windows.
 
    If pylint times out, we don't silently return an empty list -- we
    return an explicit diagnostic finding, so a timeout is visible in the
    review rather than looking indistinguishable from "no issues found."
    """
    target_path = os.path.join(repo_path, "app")
    if not os.path.exists(target_path):
        target_path = repo_path
 
    try:
        result = subprocess.run(
            [
                "pylint",
                target_path,
                "--output-format=json",
                "--recursive=y",
                "--disable=import-error",
                "--persistent=n",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        data = json.loads(result.stdout) if result.stdout.strip() else []
    except subprocess.TimeoutExpired:
        print(f"Pylint timed out after 120s scanning {target_path}")
        return [{
            "agent_type": "static_analysis_pylint",
            "file_path": target_path,
            "line_number": None,
            "severity": "low",
            "message": "Pylint timed out after 120s -- results incomplete for this run, not a clean pass.",
        }]
    except (json.JSONDecodeError, FileNotFoundError) as e:
        print(f"Pylint run failed, skipping: {e}")
        return [{
            "agent_type": "static_analysis_pylint",
            "file_path": target_path,
            "line_number": None,
            "severity": "low",
            "message": f"Pylint could not complete: {e}",
        }]
 
    findings = []
    for issue in data:
        findings.append({
            "agent_type": "static_analysis_pylint",
            "file_path": issue.get("path", "unknown"),
            "line_number": issue.get("line"),
            "severity": PYLINT_SEVERITY_MAP.get(issue.get("type", "convention"), "low"),
            "message": f"[{issue.get('symbol')}] {issue.get('message', '')}",
        })
 
    # Pylint is noisy by default (whitespace, missing docstrings, etc.)
    # Filter to medium-severity-and-above only, so this doesn't drown
    # out genuinely important findings with pure style nitpicks.
    findings = [f for f in findings if f["severity"] in ("medium", "high", "critical")]
 
    return findings
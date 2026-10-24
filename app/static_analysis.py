"""
Runs real, deterministic static analysis tools (bandit, pylint) and converts
their output into the same finding-dict shape our AI agents use.
 
A PR reviewer should report on what the PR CHANGED, not re-report the whole
repository on every review -- so both tools are pointed only at the Python
files touched by the pull request's diff.
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
 
BANDIT_TIMEOUT_SECONDS = 60
PYLINT_TIMEOUT_SECONDS = 120
 
 
def extract_changed_python_files(diff_text: str) -> list[str]:
    """
    Pull the paths of changed .py files out of a unified diff.
    Each file's new version is announced by a line like '+++ b/app/main.py'.
    Deleted files show '+++ /dev/null', so they are skipped automatically.
    """
    files = []
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            path = line[len("+++ b/"):].strip()
            if path.endswith(".py") and path not in files:
                files.append(path)
    return files
 
 
def _resolve_targets(repo_path: str, files: list[str]) -> list[str]:
    """
    Turn repo-relative paths from the diff into real file paths on disk.
 
    The paths come from a pull request, which is untrusted input, so we
    refuse anything that resolves outside the cloned repo (e.g. a file
    named '../../something.py') and anything that doesn't exist.
    """
    base = os.path.realpath(repo_path)
    targets = []
    for relative_path in files:
        full_path = os.path.realpath(os.path.join(base, relative_path))
        try:
            inside_repo = os.path.commonpath([base, full_path]) == base
        except ValueError:
            inside_repo = False
        if inside_repo and os.path.isfile(full_path):
            targets.append(full_path)
    return targets
 
 
def _repo_relative(path: str, repo_path: str) -> str:
    """Show findings with repo-relative paths (app/main.py), not machine paths."""
    base = os.path.realpath(repo_path)
    return os.path.relpath(path, base).replace("\\", "/")
 
 
def run_bandit(repo_path: str, files: list[str] | None = None) -> list[dict]:
    """
    Run bandit on the given changed files. Returns [] if there is nothing
    to scan, and a single diagnostic finding if bandit itself fails.
    """
    if files is None:
        files = []
    targets = _resolve_targets(repo_path, files)
    if not targets:
        return []
 
    try:
        # check=False: bandit exits non-zero when it FINDS issues -- expected.
        # The command is a fixed list; target paths were validated above and
        # are absolute, so they can never be read as command-line options.
        result = subprocess.run(
            ["bandit", "-f", "json", *targets],
            capture_output=True,
            text=True,
            timeout=BANDIT_TIMEOUT_SECONDS,
            check=False,
        )
        data = json.loads(result.stdout) if result.stdout.strip() else {}
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError) as e:
        print(f"Bandit run failed, skipping: {e}")
        return [{
            "agent_type": "static_analysis_bandit",
            "file_path": "(changed files)",
            "line_number": None,
            "severity": "low",
            "message": f"Bandit could not complete: {e}",
        }]
 
    findings = []
    for issue in data.get("results", []):
        findings.append({
            "agent_type": "static_analysis_bandit",
            "file_path": _repo_relative(issue.get("filename", "unknown"), repo_path),
            "line_number": issue.get("line_number"),
            "severity": BANDIT_SEVERITY_MAP.get(issue.get("issue_severity", "LOW"), "low"),
            "message": f"[{issue.get('test_id')}] {issue.get('issue_text', '')}",
        })
 
    # Bandit reports files it could not parse (for example a syntax error)
    # in a separate "errors" list and silently skips them. Surface those as
    # findings, so an unscanned file never looks the same as a clean one.
    for error in data.get("errors", []):
        findings.append({
            "agent_type": "static_analysis_bandit",
            "file_path": _repo_relative(error.get("filename", "unknown"), repo_path),
            "line_number": None,
            "severity": "medium",
            "message": f"Bandit could not analyze this file: {error.get('reason', 'unknown reason')}",
        })
 
    return findings
 
 
def run_pylint(repo_path: str, files: list[str] | None = None) -> list[dict]:
    """
    Run pylint on the given changed files.
 
    --disable=import-error stops pylint from importing heavy dependencies,
    and no --jobs flag is used because parallel mode hangs on Windows.
    A timeout is reported as an explicit finding, never as a silent clean pass.
    """
    if files is None:
        files = []
    targets = _resolve_targets(repo_path, files)
    if not targets:
        return []
 
    try:
        result = subprocess.run(
            [
                "pylint",
                *targets,
                "--output-format=json",
                "--disable=import-error",
                "--persistent=n",
            ],
            capture_output=True,
            text=True,
            timeout=PYLINT_TIMEOUT_SECONDS,
            check=False,
        )
        data = json.loads(result.stdout) if result.stdout.strip() else []
    except subprocess.TimeoutExpired:
        print(f"Pylint timed out after {PYLINT_TIMEOUT_SECONDS}s")
        return [{
            "agent_type": "static_analysis_pylint",
            "file_path": "(changed files)",
            "line_number": None,
            "severity": "low",
            "message": f"Pylint timed out after {PYLINT_TIMEOUT_SECONDS}s -- results incomplete, not a clean pass.",
        }]
    except (json.JSONDecodeError, FileNotFoundError) as e:
        print(f"Pylint run failed, skipping: {e}")
        return [{
            "agent_type": "static_analysis_pylint",
            "file_path": "(changed files)",
            "line_number": None,
            "severity": "low",
            "message": f"Pylint could not complete: {e}",
        }]
 
    findings = []
    for issue in data:
        findings.append({
            "agent_type": "static_analysis_pylint",
            "file_path": _repo_relative(issue.get("path", "unknown"), repo_path),
            "line_number": issue.get("line"),
            "severity": PYLINT_SEVERITY_MAP.get(issue.get("type", "convention"), "low"),
            "message": f"[{issue.get('symbol')}] {issue.get('message', '')}",
        })
 
    # Pylint is noisy by default; keep medium severity and above.
    return [f for f in findings if f["severity"] in ("medium", "high", "critical")]
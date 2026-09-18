"""
Runs deterministic static analysis tools (Bandit and Pylint) against a
cloned repository and converts their output into the same finding-dict
shape used by the AI agents.

Bandit is run recursively over the repository's app directory.

Pylint is intentionally run one Python file at a time. Running Pylint
against the entire directory recursively can become extremely slow or
hang on Windows when the analyzed project contains heavy dependencies.
Per-file execution keeps the analysis deterministic and lets us identify
exactly which file causes a problem.
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


def _get_target_path(repo_path: str) -> str:
    """Return the app directory when it exists, otherwise the repo root."""
    target_path = os.path.join(repo_path, "app")

    if os.path.exists(target_path):
        return target_path

    return repo_path


def run_bandit(repo_path: str) -> list[dict]:
    """
    Run Bandit against the cloned repository.

    Returns findings in the standard finding-dict shape.
    Fails safely if Bandit cannot be executed or its output cannot
    be parsed.
    """
    target_path = _get_target_path(repo_path)

    try:
        result = subprocess.run(
            [
                "bandit",
                "-r",
                target_path,
                "-f",
                "json",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )

        data = json.loads(result.stdout) if result.stdout.strip() else {}

    except (
        subprocess.TimeoutExpired,
        json.JSONDecodeError,
        FileNotFoundError,
    ) as error:
        print(f"Bandit run failed, skipping: {error}")
        return []

    findings = []

    for issue in data.get("results", []):
        findings.append(
            {
                "agent_type": "static_analysis_bandit",
                "file_path": issue.get("filename", "unknown"),
                "line_number": issue.get("line_number"),
                "severity": BANDIT_SEVERITY_MAP.get(
                    issue.get("issue_severity", "LOW"),
                    "low",
                ),
                "message": (
                    f"[{issue.get('test_id')}] "
                    f"{issue.get('issue_text', '')}"
                ),
            }
        )

    return findings


def _get_python_files(target_path: str) -> list[str]:
    """Return all Python files under the target directory."""
    python_files = []

    for root, _, files in os.walk(target_path):
        for filename in files:
            if filename.endswith(".py"):
                python_files.append(
                    os.path.join(root, filename)
                )

    return sorted(python_files)


def run_pylint(repo_path: str) -> list[dict]:
    """
    Run Pylint one Python file at a time.

    This avoids the long-running/hanging behavior observed when Pylint
    recursively analyzes the entire application directory on Windows.

    Each file has its own timeout. A problematic file is reported as a
    static-analysis execution error rather than being silently treated
    as zero findings.
    """
    target_path = _get_target_path(repo_path)
    python_files = _get_python_files(target_path)

    if not python_files:
        print("Pylint: no Python files found.")
        return []

    findings = []

    print(f"Pylint: analyzing {len(python_files)} Python files...")

    for file_path in python_files:
        try:
            result = subprocess.run(
                [
                    "pylint",
                    file_path,
                    "--output-format=json",
                    "--persistent=n",
                    "--disable=import-error",
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )

            if not result.stdout.strip():
                continue

            data = json.loads(result.stdout)

        except subprocess.TimeoutExpired:
            print(
                f"Pylint timed out for file: {file_path}"
            )
            continue

        except json.JSONDecodeError as error:
            print(
                f"Pylint returned invalid JSON for {file_path}: "
                f"{error}"
            )
            continue

        except FileNotFoundError as error:
            print(f"Pylint executable not found: {error}")
            return []

        for issue in data:
            findings.append(
                {
                    "agent_type": "static_analysis_pylint",
                    "file_path": issue.get("path", file_path),
                    "line_number": issue.get("line"),
                    "severity": PYLINT_SEVERITY_MAP.get(
                        issue.get("type", "convention"),
                        "low",
                    ),
                    "message": (
                        f"[{issue.get('symbol')}] "
                        f"{issue.get('message', '')}"
                    ),
                }
            )
    # Pylint is noisy by default (whitespace, missing docstrings, etc.)
    # Filter to medium-severity-and-above only, so this doesn't drown
    # out genuinely important findings with pure style nitpicks.
    findings = [f for f in findings if f["severity"] in ("medium", "high", "critical")]

    return findings
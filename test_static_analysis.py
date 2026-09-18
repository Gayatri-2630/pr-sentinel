"""
Standalone test for both static analysis integrations.
"""

from app.static_analysis import run_bandit, run_pylint


REPO_PATH = "./repo_clones/Gayatri-2630__pr-sentinel"


print("=" * 60)
print("STATIC ANALYSIS TEST")
print("=" * 60)


print("\nRunning Bandit...")
bandit_findings = run_bandit(REPO_PATH)

print(f"Found {len(bandit_findings)} Bandit findings:\n")

for finding in bandit_findings:
    print(
        f"- [{finding['severity'].upper()}] "
        f"{finding['file_path']} "
        f"line {finding['line_number']}: "
        f"{finding['message']}"
    )


print("\n" + "=" * 60)
print("Running Pylint...")
print("=" * 60)

pylint_findings = run_pylint(REPO_PATH)

print(
    f"\nFound {len(pylint_findings)} Pylint findings "
    f"(showing first 15):\n"
)

for finding in pylint_findings[:15]:
    print(
        f"- [{finding['severity'].upper()}] "
        f"{finding['file_path']} "
        f"line {finding['line_number']}: "
        f"{finding['message']}"
    )


print("\n" + "=" * 60)
print("STATIC ANALYSIS TEST COMPLETE")
print("=" * 60)
"""
Merge findings that several tools report for the same problem.

Example: one hardcoded password can be reported by the security agent, the
style agent and Bandit. Readers should see it once, with every tool that
agreed listed, not three separate comments.

Two findings are merged only when they are in the same file, on the same
line, AND are about the same topic. Findings with no recognised topic are
never merged, so two different problems on one line are not lost.
"""

SEVERITY_ORDER = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}

# Which source's wording is kept when findings are merged (first = preferred).
SOURCE_PRIORITY = [
    "security",
    "logic",
    "static_analysis_bandit",
    "style",
    "static_analysis_pylint",
]

# Checked in order; the first topic with a matching keyword wins.
_TOPICS = [
    ("unused", ("unused",)),
    ("secret", ("hardcoded", "hard-coded", "password", "secret", "credential", "api key")),
    ("sql", ("sql",)),
]


def _topic(message: str):
    text = str(message).lower()
    for name, keywords in _TOPICS:
        if any(word in text for word in keywords):
            return name
    return None


def _severity_rank(severity) -> int:
    return SEVERITY_ORDER.get(str(severity).lower(), 0)


def _source_rank(finding: dict) -> int:
    source = finding.get("agent_type", "")
    if source in SOURCE_PRIORITY:
        return SOURCE_PRIORITY.index(source)
    return len(SOURCE_PRIORITY)


def merge_duplicate_findings(findings: list[dict]) -> list[dict]:
    """Return a new list where duplicate findings are combined into one.

    The merged finding keeps the wording of the highest-priority source, the
    highest severity, verified=True if any source verified it, and lists the
    other tools in "also_reported_by". The input list is not modified.
    """
    groups: dict = {}
    for index, finding in enumerate(findings):
        topic = _topic(finding.get("message", ""))
        if topic:
            key = (finding["file_path"], finding["line_number"], topic)
        else:
            key = ("__unique__", index)
        groups.setdefault(key, []).append(finding)

    merged = []
    for group in groups.values():
        if len(group) == 1:
            merged.append(group[0])
            continue
        primary = min(group, key=_source_rank)
        result = dict(primary)
        result["severity"] = max((g["severity"] for g in group), key=_severity_rank)
        result["verified"] = any(g.get("verified") for g in group)
        others = {g.get("agent_type", "unknown") for g in group}
        others.discard(primary.get("agent_type", "unknown"))
        result["also_reported_by"] = sorted(others)
        merged.append(result)
    return merged

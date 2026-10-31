from app.findings_merge import merge_duplicate_findings


def make(agent, severity, line, message, verified=True, file_path="app/x.py"):
    return {
        "agent_type": agent,
        "severity": severity,
        "file_path": file_path,
        "line_number": line,
        "message": message,
        "verified": verified,
    }


def test_same_secret_reported_three_times_becomes_one():
    findings = [
        make("security", "high", 2, "Hardcoded credential detected in variable 'password'."),
        make("style", "medium", 2, "Hardcoded secret or password stored directly in source code."),
        make("static_analysis_bandit", "low", 2, "[B105] Possible hardcoded password: 'hunter2'"),
    ]
    merged = merge_duplicate_findings(findings)
    assert len(merged) == 1
    assert merged[0]["agent_type"] == "security"
    assert merged[0]["severity"] == "high"
    assert merged[0]["also_reported_by"] == ["static_analysis_bandit", "style"]


def test_different_lines_are_not_merged():
    findings = [
        make("security", "high", 2, "Hardcoded password"),
        make("static_analysis_bandit", "low", 9, "[B105] Possible hardcoded password"),
    ]
    assert len(merge_duplicate_findings(findings)) == 2


def test_different_topics_on_same_line_are_not_merged():
    findings = [
        make("style", "low", 1, "Unused import 'pickle'."),
        make("security", "high", 1, "Hardcoded password"),
    ]
    assert len(merge_duplicate_findings(findings)) == 2


def test_unrecognised_topics_are_never_merged():
    findings = [
        make("logic", "medium", 5, "Off-by-one error in loop bound."),
        make("logic", "medium", 5, "Off-by-one error in loop bound."),
    ]
    assert len(merge_duplicate_findings(findings)) == 2


def test_different_files_are_not_merged():
    findings = [
        make("security", "high", 2, "Hardcoded password", file_path="a.py"),
        make("static_analysis_bandit", "low", 2, "Possible hardcoded password", file_path="b.py"),
    ]
    assert len(merge_duplicate_findings(findings)) == 2


def test_verified_if_any_source_verified_it():
    findings = [
        make("security", "high", 2, "Hardcoded password", verified=False),
        make("static_analysis_bandit", "low", 2, "Possible hardcoded password", verified=True),
    ]
    assert merge_duplicate_findings(findings)[0]["verified"] is True


def test_severity_comparison_ignores_case():
    findings = [
        make("style", "LOW", 3, "Unused import 'os'."),
        make("static_analysis_pylint", "MEDIUM", 3, "[unused-import] Unused import os"),
    ]
    merged = merge_duplicate_findings(findings)
    assert len(merged) == 1
    assert merged[0]["severity"] == "MEDIUM"


def test_input_is_not_modified():
    findings = [
        make("security", "high", 2, "Hardcoded password"),
        make("static_analysis_bandit", "low", 2, "Possible hardcoded password"),
    ]
    before = [dict(f) for f in findings]
    merge_duplicate_findings(findings)
    assert findings == before


def test_empty_and_single():
    assert merge_duplicate_findings([]) == []
    one = make("logic", "low", 1, "Something odd")
    assert merge_duplicate_findings([one]) == [one]
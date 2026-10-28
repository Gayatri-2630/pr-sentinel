"""
PR Sentinel evaluation harness.

Run from the project root (the folder that contains `app/` and `eval/`):

    python -m eval.run_eval                # run all cases (resumes from cache)
    python -m eval.run_eval --limit 3      # quick smoke test
    python -m eval.run_eval --force        # ignore cached results
    python -m eval.run_eval --report-only  # just rebuild the report

Each case is run through the real pipeline once (`run_all_agents`). Every
variant below is computed from that single run, so there are no extra LLM calls.

Scoring rules (kept simple on purpose):
- Only security + logic AI findings and Bandit findings are scored. Style and
  Pylint findings are subjective/noisy and are reported separately.
- A finding is a true positive if it is in the right file and within +/-3 lines
  of a labeled bug line. A bug counts as found if at least one finding matches.
- Any scored finding that matches no bug is a false positive (this includes
  every scored finding on clean cases).
"""

import argparse
import json
import tempfile
import time
from pathlib import Path

from app.agents.orchestrator import run_all_agents
from eval.cases import CASES

try:
    from app.llm_client import get_and_clear_usage_log
except Exception:  # pragma: no cover
    get_and_clear_usage_log = None

RESULTS_DIR = Path(__file__).parent / "results"
CACHE_DIR = RESULTS_DIR / "cases"
FILE_PATH = "app/sample.py"
LINE_TOLERANCE = 3
SCORED_AI = {"security", "logic"}
BANDIT = "static_analysis_bandit"


# ---------- building the input ----------

def make_diff(code: str) -> str:
    lines = code.splitlines()
    body = "\n".join("+" + line for line in lines)
    return (
        f"diff --git a/{FILE_PATH} b/{FILE_PATH}\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        f"+++ b/{FILE_PATH}\n"
        f"@@ -0,0 +1,{len(lines)} @@\n"
        f"{body}\n"
    )


def expected_lines(case) -> list[int]:
    lines = case["code"].splitlines()
    result = []
    for needle in case["expected"]:
        hits = [i + 1 for i, line in enumerate(lines) if needle in line]
        if len(hits) != 1:
            raise ValueError(
                f"{case['id']}: marker {needle!r} matched {len(hits)} lines"
            )
        result.append(hits[0])
    return result


# ---------- running ----------

def run_case(case) -> dict:
    with tempfile.TemporaryDirectory() as repo:
        target = Path(repo) / FILE_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(case["code"], encoding="utf-8")

        if get_and_clear_usage_log:
            get_and_clear_usage_log()

        start = time.time()
        findings, ai_status = run_all_agents(make_diff(case["code"]), repo)
        elapsed = time.time() - start

        calls, tokens = 0, 0
        if get_and_clear_usage_log:
            try:
                log = get_and_clear_usage_log() or []
                calls = len(log)
                for entry in log:
                    if isinstance(entry, dict):
                        tokens += int(entry.get("total_tokens", 0) or 0)
            except Exception:
                pass

    return {
        "id": case["id"],
        "findings": findings,
        "ai_status": ai_status if isinstance(ai_status, dict) else str(ai_status),
        "seconds": round(elapsed, 1),
        "llm_calls": calls,
        "tokens": tokens,
    }


def degraded(result) -> bool:
    status = result["ai_status"]
    if not isinstance(status, dict):
        return False
    for agent in SCORED_AI:
        value = status.get(agent)
        if isinstance(value, dict):
            value = value.get("status")
        if value is not None and str(value).lower() != "ok":
            return True
    return False


# ---------- scoring ----------

VARIANTS = {
    "Bandit only": lambda f: f["agent_type"] == BANDIT,
    "AI agents only (unverified)": lambda f: f["agent_type"] in SCORED_AI,
    "AI agents + verifier": lambda f: f["agent_type"] in SCORED_AI and f.get("verified") is True,
    "Full pipeline (no verifier)": lambda f: f["agent_type"] in SCORED_AI or f["agent_type"] == BANDIT,
    "Full pipeline (verified only)": lambda f: (f["agent_type"] in SCORED_AI and f.get("verified") is True) or f["agent_type"] == BANDIT,
}


def score(results: dict, selector, category=None):
    tp = fp = bugs = found = 0
    for case in CASES:
        if category and case["category"] != category:
            continue
        res = results.get(case["id"])
        if res is None:
            continue
        exp = expected_lines(case)
        bugs += len(exp)
        hits = [False] * len(exp)
        for f in res["findings"]:
            if not selector(f):
                continue
            line = f.get("line_number") or 0
            matched = False
            for i, el in enumerate(exp):
                if f.get("file_path") == FILE_PATH and abs(line - el) <= LINE_TOLERANCE:
                    hits[i] = True
                    matched = True
            if not matched:
                fp += 1
        found += sum(hits)
        tp += sum(hits)
    precision = tp / (tp + fp) if (tp + fp) else float("nan")
    recall = found / bugs if bugs else float("nan")
    return dict(bugs=bugs, found=found, fp=fp, precision=precision, recall=recall)


def clean_false_alarm_rate(results, selector):
    clean = [c for c in CASES if c["kind"] == "clean" and c["id"] in results]
    if not clean:
        return float("nan"), 0
    flagged = sum(
        1 for c in clean
        if any(selector(f) for f in results[c["id"]]["findings"])
    )
    return flagged / len(clean), len(clean)


def pct(x):
    return "n/a" if x != x else f"{x * 100:.0f}%"


def build_report(results) -> str:
    n_bug = sum(1 for c in CASES if c["kind"] == "bug" and c["id"] in results)
    n_clean = sum(1 for c in CASES if c["kind"] == "clean" and c["id"] in results)
    total_tokens = sum(r["tokens"] for r in results.values())
    total_calls = sum(r["llm_calls"] for r in results.values())
    secs = [r["seconds"] for r in results.values()]

    out = ["# PR Sentinel evaluation", ""]
    out.append(f"Cases scored: {n_bug} buggy files, {n_clean} clean files "
               f"(line tolerance +/-{LINE_TOLERANCE}).")
    out.append("")
    out.append("| Variant | Bugs found | Recall | False positives | Precision | Clean files flagged |")
    out.append("|---|---|---|---|---|---|")
    for name, sel in VARIANTS.items():
        s = score(results, sel)
        far, nc = clean_false_alarm_rate(results, sel)
        out.append(f"| {name} | {s['found']}/{s['bugs']} | {pct(s['recall'])} | "
                   f"{s['fp']} | {pct(s['precision'])} | {pct(far)} of {nc} |")

    out += ["", "## Recall by category (full pipeline, verified only)", "",
            "| Category | Found | Recall |", "|---|---|---|"]
    sel = VARIANTS["Full pipeline (verified only)"]
    for cat in sorted({c["category"] for c in CASES if c["kind"] == "bug"}):
        s = score(results, sel, cat)
        out.append(f"| {cat} | {s['found']}/{s['bugs']} | {pct(s['recall'])} |")

    out += ["", "## Cost and speed", ""]
    if secs:
        out.append(f"- Mean time per case: {sum(secs) / len(secs):.1f}s "
                   f"(max {max(secs):.1f}s)")
    out.append(f"- LLM calls logged: {total_calls}; tokens logged: {total_tokens}")
    out += ["", "## Notes", "",
            "- Single run per case, so results can vary run to run (LLM output is not deterministic).",
            "- Small synthetic cases; real-world precision and recall will differ.",
            "- Style and Pylint findings are not scored."]
    return "\n".join(out) + "\n"


# ---------- main ----------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--sleep", type=float, default=0.0,
                        help="seconds to wait between cases")
    args = parser.parse_args()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for case in CASES:           # validate all labels before spending money
        expected_lines(case)

    results = {}
    todo = CASES[: args.limit] if args.limit else CASES
    for case in CASES:
        cache = CACHE_DIR / f"{case['id']}.json"
        if cache.exists() and not args.force:
            cached = json.loads(cache.read_text())
            if not degraded(cached):
                results[case["id"]] = cached

    if not args.report_only:
        for case in todo:
            if case["id"] in results:
                print(f"[cached] {case['id']}")
                continue
            print(f"[run]    {case['id']} ...", flush=True)
            res = run_case(case)
            if degraded(res):
                print(f"         DEGRADED (quota/errors): {res['ai_status']} -- not cached, rerun later")
                continue
            (CACHE_DIR / f"{case['id']}.json").write_text(json.dumps(res, indent=2))
            results[case["id"]] = res
            if args.sleep:
                time.sleep(args.sleep)

    report = build_report(results)
    (RESULTS_DIR / "report.md").write_text(report, encoding="utf-8")
    print("\n" + report)
    print(f"Saved to {RESULTS_DIR / 'report.md'}")


if __name__ == "__main__":
    main()

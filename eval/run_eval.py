"""
PR Sentinel evaluation harness (v2: multiple sets, repeated runs).

Run from the project root (the folder that contains `app/` and `eval/`):

    python -m eval.run_eval                      # v1 set, 1 run per case
    python -m eval.run_eval --set v2 --repeats 3 # harder set, 3 runs per case
    python -m eval.run_eval --set v2 --limit 2   # quick smoke test
    python -m eval.run_eval --set v2 --report-only
    python -m eval.run_eval --force              # ignore cached results

Each case is run through the real pipeline (`run_all_agents`). All variants are
computed from that one run per case, so there are no extra LLM calls.

Scoring (kept simple on purpose):
- Only security + logic AI findings and Bandit findings are scored. Style and
  Pylint findings are subjective/noisy and are not scored.
- A finding is a true positive if it is in the right file and within +/-3 lines
  of a labeled bug line. A bug counts as found if at least one finding matches.
- Any scored finding that matches no bug is a false positive (this includes
  every scored finding on clean files).
- With --repeats N, every metric is computed per repeat, then reported as the
  mean with the min-max range.
"""

import argparse
import importlib
import json
import tempfile
import time
from pathlib import Path

from app.agents.orchestrator import run_all_agents

try:
    from app.llm_client import get_and_clear_usage_log
except Exception:  # pragma: no cover
    get_and_clear_usage_log = None

BASE_DIR = Path(__file__).parent / "results"
FILE_PATH = "app/sample.py"
LINE_TOLERANCE = 3
INR_PER_USD = 90  # rough conversion, only for cost printouts
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
            raise ValueError(f"{case['id']}: marker {needle!r} matched {len(hits)} lines")
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

        calls, tokens, cost = 0, 0, 0.0
        if get_and_clear_usage_log:
            try:
                log = get_and_clear_usage_log() or []
                calls = len(log)
                for entry in log:
                    if isinstance(entry, dict):
                        tokens += int(entry.get("input_tokens", 0) or 0) + int(entry.get("output_tokens", 0) or 0)
                        cost += float(entry.get("cost_estimate", 0) or 0)
            except Exception:
                pass

    return {
        "id": case["id"],
        "findings": findings,
        "ai_status": ai_status if isinstance(ai_status, dict) else str(ai_status),
        "seconds": round(elapsed, 1),
        "llm_calls": calls,
        "tokens": tokens,
        "cost_usd": round(cost, 6),
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
MAIN_VARIANT = "Full pipeline (verified only)"


def score_run(cases, run, selector, category=None):
    """Score one repeat. `run` maps case id -> result."""
    fp = bugs = found = 0
    clean_total = clean_flagged = 0
    found_ids = set()
    for case in cases:
        if category and case["category"] != category:
            continue
        res = run.get(case["id"])
        if res is None:
            continue
        exp = expected_lines(case)
        bugs += len(exp)
        hits = [False] * len(exp)
        case_fp = 0
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
                case_fp += 1
        fp += case_fp
        found += sum(hits)
        for i, h in enumerate(hits):
            if h:
                found_ids.add((case["id"], i))
        if case["kind"] == "clean":
            clean_total += 1
            if any(selector(f) for f in res["findings"]):
                clean_flagged += 1
    precision = found / (found + fp) if (found + fp) else None
    recall = found / bugs if bugs else None
    return dict(bugs=bugs, found=found, fp=fp, precision=precision, recall=recall,
                clean_total=clean_total, clean_flagged=clean_flagged, found_ids=found_ids)


def fmt_range(values, as_pct=True):
    vals = [v for v in values if v is not None]
    if not vals:
        return "n/a"
    mean = sum(vals) / len(vals)
    if as_pct:
        text = f"{mean * 100:.0f}%"
        if len(vals) > 1 and min(vals) != max(vals):
            text += f" ({min(vals) * 100:.0f}-{max(vals) * 100:.0f}%)"
    else:
        text = f"{mean:.1f}"
        if len(vals) > 1 and min(vals) != max(vals):
            text += f" ({min(vals):g}-{max(vals):g})"
    return text


def build_report(set_name, cases, runs) -> str:
    """`runs` is a list (one entry per repeat) of dict case id -> result."""
    runs = [r for r in runs if r]
    n_bug = sum(1 for c in cases if c["kind"] == "bug")
    n_clean = sum(1 for c in cases if c["kind"] == "clean")
    all_results = [res for run in runs for res in run.values()]
    secs = [r["seconds"] for r in all_results]

    out = [f"# PR Sentinel evaluation ({set_name})", ""]
    out.append(f"{n_bug} buggy files, {n_clean} clean files, {len(runs)} run(s) per case "
               f"(line tolerance +/-{LINE_TOLERANCE}). Ranges show min-max across runs.")
    out.append("")
    out.append("| Variant | Recall | False positives (per run) | Precision | Clean files flagged |")
    out.append("|---|---|---|---|---|")
    for name, sel in VARIANTS.items():
        scores = [score_run(cases, run, sel) for run in runs]
        flagged = [s["clean_flagged"] / s["clean_total"] for s in scores if s["clean_total"]]
        out.append(
            f"| {name} | {fmt_range([s['recall'] for s in scores])} | "
            f"{fmt_range([s['fp'] for s in scores], as_pct=False)} | "
            f"{fmt_range([s['precision'] for s in scores])} | {fmt_range(flagged)} |"
        )

    sel = VARIANTS[MAIN_VARIANT]
    out += ["", f"## Recall by category ({MAIN_VARIANT}, mean over runs)", "",
            "| Category | Recall |", "|---|---|"]
    for cat in sorted({c["category"] for c in cases if c["kind"] == "bug"}):
        scores = [score_run(cases, run, sel, cat) for run in runs]
        out.append(f"| {cat} | {fmt_range([s['recall'] for s in scores])} |")

    if len(runs) > 1:
        scores = [score_run(cases, run, sel) for run in runs]
        total = scores[0]["bugs"]
        in_all = set.intersection(*(s["found_ids"] for s in scores))
        in_any = set.union(*(s["found_ids"] for s in scores))
        out += ["", "## Consistency across runs", "",
                f"- Bugs found in every run: {len(in_all)}/{total}",
                f"- Bugs found in at least one run: {len(in_any)}/{total}"]

    # Misses: which bugs were not found in the main variant (any run)
    missed = []
    for case in cases:
        if case["kind"] != "bug":
            continue
        for run in runs:
            res = run.get(case["id"])
            if res is None:
                continue
            s = score_run([case], {case["id"]: res}, sel)
            if s["found"] < s["bugs"]:
                missed.append(case["id"])
                break
    out += ["", "## Bugs missed in at least one run", "",
            ", ".join(missed) if missed else "none"]

    out += ["", "## Speed", ""]
    if secs:
        out.append(f"- Mean time per case: {sum(secs) / len(secs):.1f}s (max {max(secs):.1f}s)")
        out.append(f"- LLM calls logged: {sum(r['llm_calls'] for r in all_results)}")
        total_usd = sum(r.get("cost_usd", 0) for r in all_results)
        total_tokens = sum(r.get("tokens", 0) for r in all_results)
        out.append(f"- Tokens logged: {total_tokens}; estimated cost: ${total_usd:.3f} "
                   f"(about Rs {total_usd * INR_PER_USD:.0f} at Rs {INR_PER_USD}/USD)")
    out += ["", "## Notes", "",
            "- Synthetic cases written by the author; real-world results will differ.",
            "- LLM output is not deterministic, hence the repeated runs.",
            "- Style and Pylint findings are not scored."]
    return "\n".join(out) + "\n"


# ---------- main ----------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", default="v1", choices=["v1", "v2", "v3"])
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--sleep", type=float, default=0.0, help="seconds between cases")
    parser.add_argument("--only", default="", help="comma-separated case ids to run")
    parser.add_argument("--tag", default="", help="separate results folder, e.g. --tag min")
    parser.add_argument("--max-cost-inr", type=float, default=0.0,
                        help="stop when this run has spent about this many rupees (0 = no limit)")
    args = parser.parse_args()

    modules = {"v1": "eval.cases", "v2": "eval.cases_v2", "v3": "eval.cases_v3"}
    cases = importlib.import_module(modules[args.set]).CASES
    folder = "" if args.set == "v1" else args.set
    if args.tag:
        folder = f"{args.set}_{args.tag}"
    results_dir = BASE_DIR / folder if folder else BASE_DIR
    cache_dir = results_dir / "cases"
    cache_dir.mkdir(parents=True, exist_ok=True)

    for case in cases:            # validate all labels before spending money
        expected_lines(case)

    def cache_path(case, k):
        suffix = "" if k == 1 else f"__r{k}"
        return cache_dir / f"{case['id']}{suffix}.json"

    todo = cases[: args.limit] if args.limit else cases
    if args.only:
        wanted = {x.strip() for x in args.only.split(",") if x.strip()}
        unknown = wanted - {c["id"] for c in cases}
        if unknown:
            raise SystemExit(f"Unknown case ids: {sorted(unknown)}")
        todo = [c for c in cases if c["id"] in wanted]
    spent_inr = 0.0
    stop = False
    runs = [dict() for _ in range(args.repeats)]

    for k in range(1, args.repeats + 1):
        for case in cases:
            path = cache_path(case, k)
            if path.exists() and not args.force:
                cached = json.loads(path.read_text())
                if not degraded(cached):
                    runs[k - 1][case["id"]] = cached

    if not args.report_only:
        for k in range(1, args.repeats + 1):
            if stop:
                break
            for case in todo:
                if case["id"] in runs[k - 1]:
                    print(f"[cached] {case['id']} (run {k})")
                    continue
                print(f"[run]    {case['id']} (run {k}) ...", flush=True)
                res = run_case(case)
                if degraded(res):
                    print(f"         DEGRADED (quota/errors): {res['ai_status']} -- not cached, rerun later")
                    continue
                cache_path(case, k).write_text(json.dumps(res, indent=2))
                runs[k - 1][case["id"]] = res
                spent_inr += res.get("cost_usd", 0) * INR_PER_USD
                if args.max_cost_inr and spent_inr >= args.max_cost_inr:
                    print(f"STOPPING: spent about Rs {spent_inr:.0f} this run "
                          f"(limit Rs {args.max_cost_inr:.0f}). Results so far are cached.")
                    stop = True
                    break
                if args.sleep:
                    time.sleep(args.sleep)

    report = build_report(args.set, cases, runs)
    (results_dir / "report.md").write_text(report, encoding="utf-8")
    print("\n" + report)
    print(f"Saved to {results_dir / 'report.md'}")


if __name__ == "__main__":
    main()
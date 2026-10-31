"""
Print every missed bug and every false positive from cached evaluation runs.

    python -m eval.inspect_results --set v2
    python -m eval.inspect_results --set v2 --variant "AI agents + verifier"

No LLM calls are made; it only reads eval/results/.
"""

import argparse
import importlib
import json
from collections import defaultdict

from eval.run_eval import (BASE_DIR, FILE_PATH, LINE_TOLERANCE, MAIN_VARIANT,
                           VARIANTS, expected_lines)


def load_runs(cases, cache_dir):
    runs = defaultdict(dict)  # case id -> {run number: result}
    for case in cases:
        k = 1
        while True:
            suffix = "" if k == 1 else f"__r{k}"
            path = cache_dir / f"{case['id']}{suffix}.json"
            if not path.exists():
                break
            runs[case["id"]][k] = json.loads(path.read_text())
            k += 1
    return runs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", default="v2", choices=["v1", "v2", "v3"])
    parser.add_argument("--tag", default="")
    parser.add_argument("--variant", default=MAIN_VARIANT, choices=list(VARIANTS))
    args = parser.parse_args()

    modules = {"v1": "eval.cases", "v2": "eval.cases_v2", "v3": "eval.cases_v3"}
    cases = importlib.import_module(modules[args.set]).CASES
    folder = "" if args.set == "v1" else args.set
    if args.tag:
        folder = f"{args.set}_{args.tag}"
    cache_dir = (BASE_DIR / folder if folder else BASE_DIR) / "cases"
    selector = VARIANTS[args.variant]
    runs = load_runs(cases, cache_dir)

    print(f"Variant: {args.variant}\n")
    print("=== MISSED BUGS (which runs missed them) ===")
    any_missed = False
    for case in cases:
        if case["kind"] != "bug":
            continue
        exp = expected_lines(case)
        missed_runs = []
        for k, res in runs[case["id"]].items():
            for el in exp:
                hit = any(
                    selector(f) and f.get("file_path") == FILE_PATH
                    and abs((f.get("line_number") or 0) - el) <= LINE_TOLERANCE
                    for f in res["findings"]
                )
                if not hit:
                    missed_runs.append(k)
                    break
        if missed_runs:
            any_missed = True
            print(f"- {case['id']} [{case['category']}]: missed in runs {missed_runs} "
                  f"of {len(runs[case['id']])}")
    if not any_missed:
        print("none")

    print("\n=== FALSE POSITIVES (grouped across runs) ===")
    groups = defaultdict(int)
    for case in cases:
        exp = expected_lines(case)
        for k, res in runs[case["id"]].items():
            for f in res["findings"]:
                if not selector(f):
                    continue
                line = f.get("line_number") or 0
                if any(f.get("file_path") == FILE_PATH and abs(line - el) <= LINE_TOLERANCE
                       for el in exp):
                    continue
                key = (case["id"], case["kind"], f["agent_type"], f.get("severity"),
                       line, "verified" if f.get("verified") else "unverified",
                       (f.get("message") or "")[:110].replace("\n", " "))
                groups[key] += 1
    if not groups:
        print("none")
    for (cid, kind, agent, sev, line, ver, msg), n in sorted(groups.items()):
        print(f"- {cid} ({kind}) | {agent} | {sev} | line {line} | {ver} | x{n}: {msg}")


if __name__ == "__main__":
    main()
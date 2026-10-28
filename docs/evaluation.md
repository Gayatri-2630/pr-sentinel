
# PR Sentinel evaluation

Synthetic test set written by the author (20 seeded bugs, 10 clean files), single run per case. Results will differ on real code.

Cases scored: 20 buggy files, 10 clean files (line tolerance +/-3).

| Variant | Bugs found | Recall | False positives | Precision | Clean files flagged |
|---|---|---|---|---|---|
| Bandit only | 11/20 | 55% | 1 | 92% | 0% of 10 |
| AI agents only (unverified) | 20/20 | 100% | 1 | 95% | 10% of 10 |
| AI agents + verifier | 20/20 | 100% | 0 | 100% | 0% of 10 |
| Full pipeline (no verifier) | 20/20 | 100% | 2 | 91% | 10% of 10 |
| Full pipeline (verified only) | 20/20 | 100% | 1 | 95% | 0% of 10 |

## Recall by category (full pipeline, verified only)

| Category | Found | Recall |
|---|---|---|
| hardcoded_secret | 3/3 | 100% |
| logic | 6/6 | 100% |
| path_traversal | 2/2 | 100% |
| sql_injection | 3/3 | 100% |
| unsafe_deserialization | 2/2 | 100% |
| unsafe_exec | 2/2 | 100% |
| weak_crypto | 2/2 | 100% |

## Cost and speed

- Mean time per case: 23.5s (max 35.7s)
- LLM calls logged: 119; tokens logged: 0

## Notes

- Single run per case, so results can vary run to run (LLM output is not deterministic).
- Small synthetic cases; real-world precision and recall will differ.
- Style and Pylint findings are not scored.

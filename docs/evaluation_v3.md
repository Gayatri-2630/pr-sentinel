# PR Sentinel evaluation (v3)

20 buggy files, 10 clean files, 3 run(s) per case (line tolerance +/-3). Ranges show min-max across runs.

| Variant | Recall | False positives (per run) | Precision | Clean files flagged |
|---|---|---|---|---|
| Bandit only | 35% | 1.0 | 88% | 10% |
| AI agents only (unverified) | 83% (75-90%) | 1.0 | 94% (94-95%) | 10% |
| AI agents + verifier | 82% (75-85%) | 1.0 | 94% (94-94%) | 10% |
| Full pipeline (no verifier) | 93% (90-95%) | 2.0 | 90% (90-90%) | 20% |
| Full pipeline (verified only) | 92% (90-95%) | 2.0 | 90% (90-90%) | 20% |

## Recall by category (Full pipeline (verified only), mean over runs)

| Category | Recall |
|---|---|
| command_injection | 100% |
| cors | 100% |
| debug_mode | 100% |
| hardcoded_secret | 100% |
| insecure_temp_file | 100% |
| logic | 88% |
| mass_assignment | 33% (0-100%) |
| path_traversal | 100% |
| sql_injection | 100% |
| template_injection | 100% |
| unsafe_deserialization | 100% |
| weak_crypto | 100% |
| xxe | 100% |

## Consistency across runs

- Bugs found in every run: 18/20
- Bugs found in at least one run: 19/20

## Bugs missed in at least one run

v3_mass_assignment, v3_float_equal

## Speed

- Mean time per case: 13.2s (max 23.4s)
- LLM calls logged: 350
- Tokens logged: 227203; estimated cost: $0.234 (about Rs 21 at Rs 90/USD)

## Notes

- Synthetic cases written by the author; real-world results will differ.
- LLM output is not deterministic, hence the repeated runs.
- Style and Pylint findings are not scored.

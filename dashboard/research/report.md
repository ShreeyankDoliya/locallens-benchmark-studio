# GLM research pilot

Prompt run: `glm-native-pilot-v1` · started 2026-09-29T12:22:56.684664+00:00. Terminal job: `glm-terminal-pilot-v1`.

10 preselected tasks per prompt benchmark and 3 resource-selected terminal tasks; one completion/trial per model. These small samples do not establish overall model superiority.

The Coding Plan endpoint returned glm-5.3 for glm-5.2 requests. No measured GLM-5.2 score is claimed. GLM-5.3-Flash was independently verified and used as the second model.

IFEval rates use strict prompt accuracy. HumanEval/MBPP use original tests on one completion; GSM8K uses exact final-number matching; Terminal-Bench uses native verifier rewards.

| Benchmark | Model | Passed | Rate | p50 / p95 seconds | Errors |
| --- | --- | --- | --- | --- | --- |
| HumanEval | glm-5.3 | 10/10 | 100% | 8.02 / 12.61 | 0 |
| HumanEval | glm-5.3-flash | 10/10 | 100% | 18.69 / 29.12 | 0 |
| MBPP | glm-5.3 | 9/10 | 90% | 9.19 / 40.33 | 0 |
| MBPP | glm-5.3-flash | 9/10 | 90% | 7.77 / 26.27 | 0 |
| GSM8K | glm-5.3 | 9/10 | 90% | 3.29 / 7.73 | 0 |
| GSM8K | glm-5.3-flash | 10/10 | 100% | 3.93 / 7.25 | 0 |
| IFEval | glm-5.3 | 10/10 | 100% | 19.43 / 40.95 | 0 |
| IFEval | glm-5.3-flash | 8/10 | 80% | 36.50 / 66.09 | 0 |
| Terminal-Bench 2.0 | glm-5.3 | 3/3 | 100% | 120.05 / 132.16 | 0 |
| Terminal-Bench 2.0 | glm-5.3-flash | 3/3 | 100% | 176.11 / 361.40 | 0 |

Terminal latency is agent execution wall time including tools; other rows measure API response time. Percentiles use linear interpolation. Do not compare these timing definitions directly.

Coding Plan subscription usage. Actual monetary charges are unknown; token totals are not a bill. No paid service is needed for the separate local/mock workflow.

## IFEval secondary metrics

- glm-5.3: strict prompt 100.0%, loose prompt 100.0%, strict instruction 100.0%, loose instruction 100.0%.
- glm-5.3-flash: strict prompt 80.0%, loose prompt 90.0%, strict instruction 85.7%, loose instruction 92.9%.

## Reported token usage

- glm-5.3: 56,532 input / 52,879 output tokens, covering 43/43 results. See individual call records for cached usage.
- glm-5.3-flash: 62,592 input / 55,650 output tokens, covering 43/43 results. See individual call records for cached usage.

These totals exclude the separate access probes; unknown provider billing is not estimated.

## Failures

- glm-5.3 · gsm8k:1288 · The question does not specify a unit. GLM-5.3 returned 2040 minutes, equal to the reference 34 hours. The declared numeric scorer marks it wrong because it cannot infer unit equivalence; this is not an arithmetic failure.
- glm-5.3 · mbpp:313 · The prompt says print positive numbers, but its original assertions expect the first nonnegative number to be returned. Both models failed those original tests. Kept without post-hoc removal; this is not clean evidence of a coding defect.
- glm-5.3-flash · ifeval:1268 · Primary pass uses all strict upstream constraints; loose outcomes are separate.
- glm-5.3-flash · ifeval:3035 · Primary pass uses all strict upstream constraints; loose outcomes are separate.
- glm-5.3-flash · mbpp:313 · The prompt says print positive numbers, but its original assertions expect the first nonnegative number to be returned. Both models failed those original tests. Kept without post-hoc removal; this is not clean evidence of a coding defect.

## Dataset caveat

mbpp:313: The prompt says print positive numbers, but its original assertions expect the first nonnegative number to be returned. Both models failed those original tests. Kept without post-hoc removal; this is not clean evidence of a coding defect.
gsm8k:1288: The question does not specify a unit. GLM-5.3 returned 2040 minutes, equal to the reference 34 hours. The declared numeric scorer marks it wrong because it cannot infer unit equivalence; this is not an arithmetic failure.

## Hardware and provenance

```json
{
  "architecture": "arm64",
  "cpu": "arm",
  "logical_cpus": 8,
  "os": "macOS-26.6.2-arm64-arm-64bit",
  "python": "3.12.13",
  "ram_bytes": 17179869184
}
```

Terminal environments ran in Docker on the same host; amd64 images use emulation on Apple Silicon. Native task image tags and network-installed dependencies can drift.

The evidence JSON contains the exact prompts, responses, native tests, judgments, settings, source hashes, API identity/usage and agent trajectories. The dashboard can filter individual failures and disagreements.

Evidence SHA-256: `34ea0431d9fd45ce3cf2405c833e8f35fef7b9bbfa627659a8adf42707ce2405`

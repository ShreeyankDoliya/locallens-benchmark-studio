# LLM Benchmark Studio — mock-demo

Status: **completed** · Dataset: `studio-sample-v1`

Small diagnostic sample; these scores do not establish overall model superiority.

| Model | Passed / completed | Planned | Pass rate | Errors | p50 / p95 ms |
|---|---:|---:|---:|---:|---:|
| mock-steady | 19 / 20 | 20 | 95.0% | 0 | 38.13 / 50.12 |
| mock-hasty | 9 / 20 | 20 | 45.0% | 1 | 14.81 / 18.12 |

## Provenance

- Dataset SHA-256: `029a3f01fdef201fc489dc4b170e0b5a1c413752ce58d08a35308b96b8f1e479`
- Configuration SHA-256: `8dca15199576a1e10e9b70592f7cd9d43039afa5cea82c97b5c0b34e23bbae84`
- Runner SHA-256: `ec8d184daa74abe35b876fdf5aa3fd96dfff86e39623959d22d4339fcfd3dda0`
- Scorer: `deterministic-v1`
- Hardware: Scripted mock demo on the recorded host. Delays are synthetic; no inference, GPU use, or token estimates.
- Host: `{"architecture": "arm64", "cpu": "arm", "logical_cpus": 8, "os": "macOS-26.6.2-arm64-arm-64bit", "python": "3.12.13", "ram_bytes": 17179869184}`

## Interpretation

Errors count as failures. Incomplete runs use completed tasks as the denominator and show planned counts. Latency percentiles interpolate successful final request durations and exclude queue time, retry backoff and failed attempts. They include model loading when applicable. All attempts are in the JSON evidence.

Mock outputs and delays are scripted. Unknown token counts and costs stay null. Local execution has no API fee; electricity and hardware costs are not measured. Optional configured prices estimate only observed token usage, excluding failed attempts with unknown usage.

Consistency means equal pass/fail outcomes across a complete perturbation group, not identical answers. A group may consistently fail.

## Disagreements

- `code-bool`
- `code-trace-paraphrase`
- `ground-open-noise`
- `ground-unknown`
- `if-select`
- `if-sort-paraphrase`
- `json-array`
- `json-empty`
- `json-stock-paraphrase`
- `reason-crates-noise`

See the adjacent JSON file for every task, prompt, expected answer, response, scoring explanation, model manifest and attempt.

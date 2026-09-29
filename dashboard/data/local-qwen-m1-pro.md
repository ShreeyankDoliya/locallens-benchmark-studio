# LLM Benchmark Studio — local-qwen-m1-pro

Status: **completed** · Dataset: `studio-sample-v1`

Small diagnostic sample; these scores do not establish overall model superiority.

| Model | Passed / completed | Planned | Pass rate | Errors | p50 / p95 ms |
|---|---:|---:|---:|---:|---:|
| qwen-0.5b | 2 / 20 | 20 | 10.0% | 0 | 166.03 / 1609.41 |
| qwen-1.5b | 6 / 20 | 20 | 30.0% | 0 | 149.63 / 2274.69 |

## Provenance

- Dataset SHA-256: `029a3f01fdef201fc489dc4b170e0b5a1c413752ce58d08a35308b96b8f1e479`
- Configuration SHA-256: `decea9af33fd1f0b9c482f5ffec62e28192aed2e1139b93aaaf0448a3641d54d`
- Runner SHA-256: `ec8d184daa74abe35b876fdf5aa3fd96dfff86e39623959d22d4339fcfd3dda0`
- Scorer: `deterministic-v1`
- Hardware: Apple M1 Pro (8 CPU cores), Apple M1 Pro integrated GPU via Metal, 16 GiB unified RAM; macOS 26.6.2 arm64. AC power, Low Power Mode off. Normal desktop workload, not isolated; no warm-up exclusion. Ollama 0.34.4; OLLAMA_NO_CLOUD=1, OLLAMA_NUM_PARALLEL=1, OLLAMA_MAX_LOADED_MODELS=1; one request at a time. Model loads are included in request latency.
- Host: `{"architecture": "arm64", "cpu": "arm", "logical_cpus": 8, "os": "macOS-26.6.2-arm64-arm-64bit", "python": "3.12.13", "ram_bytes": 17179869184}`

## Interpretation

Errors count as failures. Incomplete runs use completed tasks as the denominator and show planned counts. Latency percentiles interpolate successful final request durations and exclude queue time, retry backoff and failed attempts. They include model loading when applicable. All attempts are in the JSON evidence.

Mock outputs and delays are scripted. Unknown token counts and costs stay null. Local execution has no API fee; electricity and hardware costs are not measured. Optional configured prices estimate only observed token usage, excluding failed attempts with unknown usage.

Consistency means equal pass/fail outcomes across a complete perturbation group, not identical answers. A group may consistently fail.

## Disagreements

- `ground-open`
- `ground-open-noise`
- `if-select-noise`
- `reason-order`

See the adjacent JSON file for every task, prompt, expected answer, response, scoring explanation, model manifest and attempt.

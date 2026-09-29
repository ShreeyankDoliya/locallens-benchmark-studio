# Methodology

LocalLens is designed to make comparisons inspectable. Its sample provides narrow diagnostic tasks rather than evidence of overall model superiority.

## Dataset: studio-sample-v1

The 20 tasks are original, hand-authored examples. Five categories contain four tasks each. Fourteen base tasks and six controlled variants share an expected answer and scoring method within each group. Category balance is deliberate and is not representative of a real workload distribution.

| Category | What it checks | What it cannot establish |
|---|---|---|
| Instruction following | Small selection and sorting operations with precise separators, casing and no commentary | Broad instruction hierarchy, long-context compliance, safety or tool use |
| Structured output | Valid JSON, expected keys, types and values; no extra prose | General schema reasoning, streaming correctness or downstream application safety |
| Reasoning | Short arithmetic, ordering and state updates | General intelligence, difficult mathematics or faithful reasoning processes |
| Grounding | Answers confined to supplied fictional context, distinguishing distractors and abstaining when a fact is absent | World knowledge accuracy, retrieval quality or resistance to prompt injection |
| Code | Predicting output from small Python snippets | Writing, running, debugging or securing real programs |

Perturbations: `if-sort` (paraphrase), `if-select` (irrelevant context), `json-stock` (paraphrase), `reason-crates` (irrelevant context), `ground-open` (irrelevant context), and `code-trace` (paraphrase). A group must have one base task and preserve category, expected answer, and scoring method. The loader rejects violations, duplicate IDs, mixed versions, duplicate JSON keys, invalid categories, unsupported scoring methods, and non-finite JSON values.

The dataset is public and tiny. Models may have seen similar task patterns; no claim of uncontaminated held-out evaluation is made. A new prompt or scoring change should use a new dataset version. The content fingerprint catches changes even if someone forgets to update that version.

## Scoring contract

All scores are binary and labeled `kind: deterministic`, with scorer version `deterministic-v1`:

- **exact**: literal string equality. Case, spaces and final newlines count.
- **normalized**: NFKC Unicode normalization, case folding, splitting and joining whitespace. Punctuation, numbers and additional explanations still count.
- **json**: parse one complete JSON value with duplicate-key and non-finite-number rejection, then compare canonical serialized structures. Object key order does not matter; array order, string/number/bool distinctions, integer/float representation and extra keys matter. Markdown fences fail.

A task's `rubric` explains its deterministic acceptance rule for the reader. It is not a model-generated judgment. No LLM judge or subjective quality score is present. A future judge must preserve its prompt, model, rubric and response and use a separately labeled score kind.

Provider errors are failed tasks with score zero and a specific error explanation. Only generation errors marked retryable (transport failures, HTTP 408/429/5xx, timeouts) are retried. A wrong answer is not retried, preventing answer selection from biasing scores. Retries apply exponential backoff starting at 250 ms, capped at 8 seconds. The mock fixture explicitly simulates one recovered error and one terminal outage.

## Aggregation

- Pass rate is passed / completed tasks, including errors in the denominator. Planned counts accompany provisional partial runs. Category rates use the same rule.
- Error rate is terminal provider-error results / completed results. A recovered retry is visible in attempt history but does not count as a terminal task error.
- Latency p50/p90/p95 use linearly interpolated quantiles of successful final request wall times, including failed-scoring responses. Attempts that return no response or a provider error are excluded from these percentiles; their separate timings remain in attempt history. Queue time and retry backoff are excluded. Successful means a valid provider response, not a passing answer.
- Disagreements are task IDs with both pass and fail outcomes among completed models in the same run. Missing model results are not inferred. Cross-run rows remain separate.
- Consistency is the fraction of complete perturbation groups with equal pass/fail outcomes. Consistently incorrect groups count, so the number of groups passing every variant is also shown. This is outcome consistency, not textual answer agreement.
- Cost, if both per-million-token rates are supplied, sums only results with observed input and output token counts. Coverage is reported; unknown usage remains null. Failed attempts may consume compute without reported usage. No local electricity or equipment estimate is implied.

## Comparison controls

Every run stores an immutable task/config snapshot and SHA-256 fingerprints, the runner source fingerprint, model manifests, timestamps, and hardware. The Ollama manifest includes the local model digest, quantization details where available, server version, native template, system prompt, model parameters and model information. Providers receive the prompt and settings, never expected answers or scoring rubrics.

The default local run executes tasks sequentially and models in configuration order, at one request start per second. A model remains loaded for up to five minutes. There is no warm-up exclusion: the first request may include load time, and later requests may benefit from caches. Because default ordering is blocked by model, host drift may affect comparisons. Shared prompt settings do not equalize native model templates. Use repeated runs and record operating conditions before interpreting timing differences. Raising concurrency also changes what latency means; it is a throughput setting, not a free speed improvement.

## Reproducibility boundaries

Re-exporting the same SQLite evidence yields byte-identical JSON. The `report` command recomputes deterministic judgments and summaries directly from published evidence. Fingerprints detect accidental changes; they are not authenticity signatures. New runs can reproduce mock pass/fail outcomes but will have different timestamps and timings. Mock latencies are intentionally scripted delays and do not model hardware or LLM speed.

Real inference may vary by model build, quantization, runtime, drivers, template, hardware, server load and kernel nondeterminism, even with a fixed seed and temperature 0. Resume checks stored source/runtime/hardware/model manifests; it cannot prove unchanged background load, GPU drivers or every environmental detail. Record GPU/VRAM and power conditions in `hardware_notes`; CPU/OS/RAM information is collected automatically. A server may continue generating after a timed-out request is cancelled. Do not modify model tags or runtime configuration during a run.

The benchmark does not sandbox or execute generated code. No significance tests, confidence intervals, judge calibration, adversarial evaluation or representative workload sampling are provided. Treat findings as examples worth investigating, not a ranking of overall model quality.

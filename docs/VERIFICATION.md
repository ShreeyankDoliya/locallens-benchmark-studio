# Verification record

Research extension: **37 Python tests and 10 browser tests pass**. The official Terminal-Bench certificate task passed all six tests with its reference solution and failed all six with a no-op agent. These are harness controls, not model scores. See [the research verification commands and limitations](RESEARCH.md#commands-and-observed-controls). No GLM API requests were sent.

Verified on 2026-09-29 using macOS arm64, 8 logical CPUs, 16 GiB RAM, Python 3.12.13 and the installed Google Chrome browser. Mock requests do not use the GPU. Automatic host details and UTC timestamps are included in each JSON report.

## Commands executed

From the repository root:

```bash
uv venv --python python3
uv pip install -e .
uv lock
uv export --frozen --no-dev --no-emit-project --format requirements-txt --output-file requirements.txt
uv sync --locked

.venv/bin/llm-bench validate datasets/studio-sample-v1.jsonl
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m compileall -q src
node --check dashboard/app.js

.venv/bin/llm-bench run --config configs/mock.json --dataset datasets/studio-sample-v1.jsonl --run-id mock-demo
.venv/bin/llm-bench export --run-id mock-demo --output dashboard/data

.venv/bin/llm-bench run --config configs/mock.json --dataset datasets/studio-sample-v1.jsonl --run-id mock-repeat --max-tasks 7
.venv/bin/llm-bench run --run-id mock-repeat --resume
.venv/bin/llm-bench export --run-id mock-repeat --output dashboard/data

.venv/bin/llm-bench report dashboard/data/mock-demo.json --output runs/reproduced-report.md
cmp dashboard/data/mock-demo.md runs/reproduced-report.md

npm install
PLAYWRIGHT_CHANNEL=chrome npm run test:ui
python3 -m http.server 8000 --bind 127.0.0.1 --directory dashboard
```

For a fresh clone, use `npm ci` to honor the npm lockfile. The initial Playwright browser download stalled on this machine and was stopped. The completed browser tests used the already installed Google Chrome through `PLAYWRIGHT_CHANNEL=chrome`. Standard CI uses Playwright's downloaded Chromium. An initial mobile test found overflow from a visually hidden table label; its scroll-container positioning was corrected and all browser tests then passed.

Run IDs are unique in SQLite. Repeating the sample-generation commands against an existing database requires new IDs, or `--resume` to finish an existing run. The committed JSON files can be inspected immediately after cloning; a fresh local SQLite database is created on the first new run.

## Results

- Dataset validation: **20 tasks**, **5 categories**, **6 perturbation groups**.
- Python suite: **31 tests passed**, including every published report and index entry.
- Browser suite: **7 tests passed**, including mobile overflow, filters, comparison, evidence, downloads, output escaping and themed dropdown keyboard controls.
- `mock-demo`: **40 completed model/task results**.
- `mock-repeat`: stopped at **7 results**, resumed to **40**, preserving saved results.
- Report reconstructed from published JSON: **byte-identical**, `cmp` exited 0.
- Source fingerprints identify the producing runner. Archived reports retain their original source fingerprint when the implementation changes later.

| Model | Passed | Pass rate | Terminal errors | p50 | p95 |
|---|---:|---:|---:|---:|---:|
| mock-steady | 19 / 20 | 95% | 0 | 38.13 ms | 50.12 ms |
| mock-hasty | 9 / 20 | 45% | 1 | 14.81 ms | 18.12 ms |

There are **10 task-level model disagreements** and **12 failed results**. The hasty mock includes one successful retry and one three-attempt terminal failure. Its six perturbation groups change pass/fail outcome, while the steady mock passes all six groups. Both intentionally fail `reason-mod`.

These timings reflect **scripted sleeps plus runtime overhead**, not model inference speed. Mock tokens and estimated cost are null. No real-model superiority claim can be made from these fixtures or this small sample dataset.

## Remaining limits

Ollama 0.34.4 was subsequently installed on this host and both configured open-weight models were evaluated successfully. The adapter also has tests for metadata, request payloads, error codes, missing token usage, malformed responses and rejection of remote/cloud configurations.

LLM judges and paid providers are future extensions. GPU details and power conditions are manual notes. There are no statistical confidence intervals, controlled warm-up runs, generated-code sandbox, or large-table pagination. The site publishes evidence only and cannot initiate local evaluations.


## Real local-model verification

The follow-up run `local-qwen-m1-pro` used Qwen2.5 0.5B and 1.5B (Q4_K_M) through Ollama 0.34.4 on an Apple M1 Pro with 16 GiB unified memory and Metal acceleration. AC power was connected and Low Power Mode was off. Normal desktop applications remained active; these are not isolated performance measurements. No scoring rules or prompts were changed after inspecting responses.

```bash
HOMEBREW_NO_AUTO_UPDATE=1 HOMEBREW_NO_INSTALL_CLEANUP=1 brew install ollama
OLLAMA_NO_CLOUD=1 OLLAMA_NUM_PARALLEL=1 OLLAMA_MAX_LOADED_MODELS=1 OLLAMA_HOST=http://127.0.0.1:11434 ollama serve > runs/ollama-server.log 2>&1
```

In another terminal:

```bash
ollama pull qwen2.5:0.5b
ollama pull qwen2.5:1.5b
ollama list
.venv/bin/llm-bench run --config configs/ollama-m1-pro.json --dataset datasets/studio-sample-v1.jsonl --run-id local-qwen-m1-pro --max-tasks 7
.venv/bin/llm-bench run --run-id local-qwen-m1-pro --resume
.venv/bin/llm-bench export --run-id local-qwen-m1-pro --output dashboard/data
.venv/bin/llm-bench report dashboard/data/local-qwen-m1-pro.json --output runs/local-qwen-reproduced.md
cmp dashboard/data/local-qwen-m1-pro.md runs/local-qwen-reproduced.md
```

The real run stopped after seven task results and resumed to 40 without replacing saved results. All 40 requests returned responses and token counts; there were no retries or provider errors. The reconstructed report was byte-identical.

| Local model | Passed | Pass rate | Errors | p50 | p95 |
|---|---:|---:|---:|---:|---:|
| Qwen2.5 0.5B | 2 / 20 | 10% | 0 | 166.03 ms | 1,609.41 ms |
| Qwen2.5 1.5B | 6 / 20 | 30% | 0 | 149.63 ms | 2,274.69 ms |

There were four task-level disagreements. The strict format checks rejected extra explanations and Markdown-fenced JSON even when the answer content was otherwise correct. Other responses contained incorrect reasoning or code-trace answers. The 256-token output limit also truncated some long explanations. These are narrow, configuration-specific observations on 20 tasks, not evidence of overall superiority or stable speed rankings. No warm-up requests were excluded.

Full model digests, quantization, native templates, generation settings, raw responses, token counts, timings and hardware notes are preserved in `dashboard/data/local-qwen-m1-pro.json`. The example machine configuration is `configs/ollama-m1-pro.json`; edit its hardware notes before using it on another computer. Homebrew installed Ollama with its MLX dependencies and upgraded its Python/readline dependencies; the benchmark continued to use the existing Python 3.12 virtual environment. Ollama was launched for this session, not registered to start at login.

The expanded CI suite exposed a request-spacing issue when a synchronous SQLite checkpoint delayed dispatch under concurrency. The limiter now records the dispatch time after checkpointing, and generation runs in the worker task under a total timeout. A regression test adds a slow checkpoint and verifies the configured spacing. The published local run used concurrency 1 and retains its original evidence and source fingerprint.

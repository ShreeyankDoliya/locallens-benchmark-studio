# Verification record

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
- Python suite: **28 tests passed**.
- Browser suite: **5 tests passed**, including mobile overflow, filters, comparison, evidence, downloads and output escaping.
- `mock-demo`: **40 completed model/task results**.
- `mock-repeat`: stopped at **7 results**, resumed to **40**, preserving saved results.
- Report reconstructed from published JSON: **byte-identical**, `cmp` exited 0.
- Source fingerprints in both exported reports match the implemented runner.

| Model | Passed | Pass rate | Terminal errors | p50 | p95 |
|---|---:|---:|---:|---:|---:|
| mock-steady | 19 / 20 | 95% | 0 | 38.13 ms | 50.12 ms |
| mock-hasty | 9 / 20 | 45% | 1 | 14.81 ms | 18.12 ms |

There are **10 task-level model disagreements** and **12 failed results**. The hasty mock includes one successful retry and one three-attempt terminal failure. Its six perturbation groups change pass/fail outcome, while the steady mock passes all six groups. Both intentionally fail `reason-mod`.

These timings reflect **scripted sleeps plus runtime overhead**, not model inference speed. Mock tokens and estimated cost are null. No real-model superiority claim can be made from these fixtures or this small sample dataset.

## Remaining limits

Ollama is not installed on the verification host, so no open-weight model was downloaded or evaluated in this session. The local adapter was tested against Ollama-shaped HTTP responses, including metadata, request payloads, error codes, missing token usage, malformed responses and rejection of remote/cloud configurations. A real local benchmark requires installing Ollama and the model tags listed in the README.

LLM judges and paid providers are future extensions. GPU details and power conditions are manual notes. There are no statistical confidence intervals, controlled warm-up runs, generated-code sandbox, or large-table pagination. The site publishes evidence only and cannot initiate local evaluations.

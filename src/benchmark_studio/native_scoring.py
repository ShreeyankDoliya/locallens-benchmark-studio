"""Research scorers: original tests/constraints, with explicit chat adaptations."""
from __future__ import annotations

import asyncio
from decimal import Decimal, InvalidOperation
import hashlib
import importlib
import json
from pathlib import Path
import re
import sys
import uuid

from .models import StrictModel


class ResearchTask(StrictModel):
    benchmark: str
    id: str
    prompt: str
    expected: dict
    protocol: str
    source_revision: str
    source_sha256: str


def build_tasks(catalog, source_dir: Path, selection: dict) -> list[ResearchTask]:
    from .research import verify_dataset
    import gzip
    tasks = []
    for source in catalog.sources:
        path = source_dir / (source.id + ('.jsonl.gz' if source.path.endswith('.gz') else '.jsonl'))
        data = path.read_bytes()
        rows = verify_dataset(data, source)
        chosen = next(s['task_ids'] for s in selection['selections'] if s['benchmark'] == source.id)
        indexed = {str(r.get('task_id', r.get('key', i))): r for i, r in enumerate(rows)}
        demos = ''
        if source.id == 'mbpp':
            all_rows = [json.loads(line) for line in data.splitlines() if line.strip()]
            for n in (2, 3, 4):
                row = next(r for r in all_rows if r['task_id'] == n)
                demos += f"Task: {row['text']}\nTests:\n" + '\n'.join(row['test_list']) + f"\n[BEGIN]\n{row['code']}\n[DONE]\n\n"
        for task_id in chosen:
            row = indexed[task_id]
            if source.id == 'humaneval':
                prompt = 'Complete the Python function below. Return only the complete Python source, including its signature, with no Markdown or explanation.\n\n' + row['prompt']
                expected = {'tests': row['test'], 'entry_point': row['entry_point']}
                protocol = 'HumanEval original tests; chat adaptation requests a complete function; one completion per task; pass@1 on a preselected subset.'
            elif source.id == 'mbpp':
                prompt = demos + f"Task: {row['text']}\nTests:\n" + '\n'.join(row['test_list']) + '\nReturn only complete Python source between [BEGIN] and [DONE].\n[BEGIN]\n'
                expected = {'test_setup_code': row.get('test_setup_code', ''), 'tests': row['test_list']}
                protocol = 'MBPP original test split; three-shot examples 2,3,4 and supplied tests; chat adaptation; one completion; excludes challenge tests.'
            elif source.id == 'gsm8k':
                prompt = row['question'] + '\n\nSolve the problem. End your response with #### followed by only the final numeric answer.'
                expected = {'answer': row['answer'].rsplit('####', 1)[1].strip()}
                protocol = 'GSM8K test subset; zero-shot chat; exact numeric match after final #### marker; not the paper learned-verifier protocol.'
            else:
                prompt = row['prompt']
                expected = {k: row[k] for k in ('key', 'instruction_id_list', 'kwargs')}
                protocol = 'IFEval original prompts and upstream checkers; strict/loose prompt and instruction outcomes reported separately.'
            tasks.append(ResearchTask(benchmark=source.id, id=task_id, prompt=prompt, expected=expected,
                                      protocol=protocol, source_revision=source.revision, source_sha256=source.sha256))
    return tasks


def numeric_answer(response: str) -> Decimal | None:
    match = re.search(r'####\s*([-+]?\d[\d,]*(?:\.\d+)?)\s*\Z', response)
    if not match:
        return None
    try:
        value = Decimal(match.group(1).replace(',', ''))
        return value if value.is_finite() else None
    except InvalidOperation:
        return None


def extract_code(response: str) -> tuple[str, str]:
    """Fixed extraction declared before inference; no model-specific repairs."""
    text = response.strip()
    if text.startswith('[BEGIN]'):
        text = text[len('[BEGIN]'):].strip()
    if text.endswith('[DONE]'):
        text = text[:-len('[DONE]')].strip()
    fenced = re.fullmatch(r'```(?:python|py)?\s*\n(.*?)\n```', text, re.DOTALL)
    if fenced:
        return fenced.group(1), 'Removed one whole-response Python fence.'
    return text, 'Trimmed surrounding whitespace and optional MBPP delimiters; no code repaired.'


async def sandbox_python(script: str, image: str, timeout: float = 20) -> dict:
    """Execute in a disposable container: no network, credentials or host mounts."""
    if '@sha256:' not in image:
        raise ValueError('Sandbox image must be pinned by digest')
    name = 'locallens-code-' + uuid.uuid4().hex
    argv = ['docker', 'run', '--rm', '-i', '--name', name, '--network', 'none', '--read-only',
            '--memory', '512m', '--cpus', '1', '--pids-limit', '64', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges', '--user', '65534:65534',
            '--tmpfs', '/tmp:rw,nosuid,size=64m', '--workdir', '/tmp',
            '--ulimit', 'cpu=10:10', '--ulimit', 'nofile=64:64', image,
            'sh', '-c', 'ulimit -f 2048; python -I - > /tmp/output 2>&1; result=$?; tail -c 16384 /tmp/output; exit "$result"']
    process = await asyncio.create_subprocess_exec(*argv, stdin=asyncio.subprocess.PIPE,
                  stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    timed_out = False
    try:
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(script.encode()), timeout)
        except TimeoutError:
            timed_out = True
            process.kill()
            stdout, stderr = await process.communicate()
        if process.returncode in (125, 126, 127) and not timed_out:
            raise RuntimeError('Docker sandbox infrastructure error: ' + stderr.decode(errors='replace')[:1000])
        return {'passed': process.returncode == 0 and not timed_out, 'exit_code': process.returncode,
                'timed_out': timed_out, 'stdout': stdout.decode(errors='replace'),
                'stderr': stderr.decode(errors='replace'), 'image': image,
                'script_sha256': hashlib.sha256(script.encode()).hexdigest()}
    finally:
        cleanup = await asyncio.create_subprocess_exec('docker', 'rm', '-f', name,
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await cleanup.wait()


def ifeval_score(task: ResearchTask, response: str, upstream: Path) -> dict:
    sys.path.insert(0, str(upstream.resolve()))
    import random
    import langdetect
    random.seed(0)
    langdetect.DetectorFactory.seed = 0
    lib = importlib.import_module('instruction_following_eval.evaluation_lib')
    inp = lib.InputExample(prompt=task.prompt, **task.expected)
    strict = lib.test_instruction_following_strict(inp, {task.prompt: response})
    loose = lib.test_instruction_following_loose(inp, {task.prompt: response})
    return {'passed': strict.follow_all_instructions, 'kind': 'deterministic', 'method': 'ifeval-upstream',
            'strict': strict.follow_instruction_list, 'loose': loose.follow_instruction_list,
            'strict_prompt': strict.follow_all_instructions, 'loose_prompt': loose.follow_all_instructions,
            'explanation': 'Primary pass uses all strict upstream constraints; loose outcomes are separate.'}


async def score_task(task: ResearchTask, response: str, *, image: str, upstream: Path) -> dict:
    if task.benchmark == 'gsm8k':
        answer = numeric_answer(response)
        expected = Decimal(task.expected['answer'].replace(',', ''))
        return {'passed': answer == expected, 'kind': 'deterministic', 'method': 'gsm8k-final-number-v1',
                'extracted': str(answer) if answer is not None else None,
                'explanation': 'Exact numeric equality after the final #### marker; commas ignored. Missing marker or trailing prose fails.'}
    if task.benchmark == 'ifeval':
        return ifeval_score(task, response, upstream)
    code, extraction = extract_code(response)
    if task.benchmark == 'humaneval':
        tests = task.expected['tests'] + '\ncheck(' + task.expected['entry_point'] + ')\n'
        script = code + '\n\n' + tests
    elif task.benchmark == 'mbpp':
        tests = '\n'.join(task.expected['tests'])
        script = task.expected['test_setup_code'] + '\n' + code + '\n\n' + tests + '\n'
    else:
        raise ValueError('Unsupported native scorer')
    outcome = await sandbox_python(script, image)
    return {**outcome, 'kind': 'deterministic', 'method': task.benchmark + '-upstream-tests-v1',
            'extraction': extraction, 'extracted_code': code,
            'explanation': 'Original upstream tests executed after generated source in an isolated Python container. Pass requires exit code 0 before timeout; no textual self-reported success is accepted.'}

"""Command line entry points; no server or API key needed for the mock workflow."""
import argparse
import asyncio
import json
from pathlib import Path
import re
import sqlite3
import sys
from datetime import datetime, timezone

from .analysis import export_run, markdown_report, verify_export
from .models import RunConfig, load_dataset, strict_json
from .providers import ProviderError
from .runner import execute
from .storage import Store


def main() -> None:
    parser = argparse.ArgumentParser(prog='llm-bench')
    sub = parser.add_subparsers(dest='command', required=True)
    validate = sub.add_parser('validate', help='Validate versioned JSONL tasks')
    validate.add_argument('dataset', type=Path)
    run = sub.add_parser('run', help='Create a run or resume its immutable snapshot')
    run.add_argument('--dataset', type=Path, default=Path('datasets/studio-sample-v1.jsonl'))
    run.add_argument('--config', type=Path, default=Path('configs/mock.json'))
    run.add_argument('--db', type=Path, default=Path('runs/studio.sqlite'))
    run.add_argument('--run-id', default=None)
    run.add_argument('--resume', action='store_true')
    run.add_argument('--max-tasks', type=int, help='Checkpoint after this many new model/task pairs')
    export = sub.add_parser('export', help='Export evidence, a report, and dashboard index')
    export.add_argument('--db', type=Path, default=Path('runs/studio.sqlite'))
    export.add_argument('--run-id', required=True)
    export.add_argument('--output', type=Path, default=Path('dashboard/data'))
    report = sub.add_parser('report', help='Verify published JSON and reproduce its Markdown report')
    report.add_argument('input', type=Path)
    report.add_argument('--output', type=Path, required=True)
    listing = sub.add_parser('list', help='List saved runs')
    listing.add_argument('--db', type=Path, default=Path('runs/studio.sqlite'))
    args = parser.parse_args()
    store = None
    try:
        if args.command == 'report':
            data = verify_export(strict_json(args.input.read_text()))
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(markdown_report(data), encoding='utf-8')
            print(f'Verified evidence; reproduced report: {args.output}')
            return
        if args.command == 'validate':
            tasks = load_dataset(args.dataset)
            print(f'Valid: {len(tasks)} tasks, {len({t.category for t in tasks})} categories, version {tasks[0].dataset_version}')
            return
        if args.command == 'run' and args.max_tasks is not None and args.max_tasks < 1:
            raise ValueError('--max-tasks must be positive')
        run_id = getattr(args, 'run_id', None)
        if run_id is not None and not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}', run_id):
            raise ValueError('run ID must be 1–80 letters, digits, underscores or hyphens')
        store = Store(args.db)
        if args.command == 'list':
            for row in store.db.execute('SELECT id,status,created_at FROM runs ORDER BY created_at'):
                print(' | '.join(row))
        elif args.command == 'export':
            print(export_run(store, run_id, args.output))
        else:
            if args.resume and not run_id:
                raise ValueError('--resume requires --run-id')
            run_id = run_id or datetime.now(timezone.utc).strftime('run-%Y%m%dT%H%M%S%fZ')
            exists = store.db.execute('SELECT 1 FROM runs WHERE id=?', (run_id,)).fetchone()
            if exists and not args.resume:
                raise ValueError('run ID exists; use --resume or a new ID')
            if args.resume and not exists:
                raise ValueError('cannot resume an unknown run')
            tasks = None if args.resume else load_dataset(args.dataset)
            config = None if args.resume else RunConfig.model_validate(strict_json(args.config.read_text()))
            print(f'Run: {run_id}', flush=True)
            asyncio.run(execute(store, run_id, tasks, config, max_new_results=args.max_tasks))
            print(f'{store.run(run_id)["status"]}: {len(store.results(run_id))} results saved')
    except KeyboardInterrupt:
        print('\nInterrupted. Resume with the same --run-id and --resume.', file=sys.stderr)
        sys.exit(130)
    except (ValueError, KeyError, TypeError, OSError, sqlite3.Error, ProviderError, TimeoutError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        sys.exit(1)
    finally:
        if store:
            store.close()


if __name__ == '__main__':
    main()

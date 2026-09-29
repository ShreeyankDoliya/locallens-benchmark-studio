"""Run native Harbor via a loopback gateway; keep the real key out of its logs.

Only two confirmed model IDs and non-streaming chat requests are accepted.
The gateway records actual returned identities and rejects silent model routing.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import getpass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import subprocess
import threading
import time

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--harbor', required=True)
    parser.add_argument('--config', type=Path, default=Path('configs/harbor-glm-pilot.json'))
    parser.add_argument('--log', type=Path, default=Path('runs/glm/harbor-api-calls.jsonl'))
    parser.add_argument('--resume', type=Path)
    args = parser.parse_args()
    key = os.environ.get('ZAI_API_KEY') or getpass.getpass('Z.ai API key (input hidden): ')
    token = secrets.token_urlsafe(32)
    endpoint = 'https://api.z.ai/api/coding/paas/v4/chat/completions'
    args.log.parent.mkdir(parents=True, exist_ok=True)
    gate = threading.Lock()
    last_start = [0.0]
    client = httpx.Client(timeout=300, trust_env=False, follow_redirects=False)

    def clean(data):
        # Redact before anything can reach disk, including provider error bodies.
        return json.loads(json.dumps(data).replace(key, '[REDACTED]').replace(token, '[LOCAL TOKEN]'))

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def send_json(self, status, body):
            raw = json.dumps(body).encode()
            self.send_response(status); self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw)
        def do_POST(self):
            if self.path != '/v1/chat/completions' or not secrets.compare_digest(self.headers.get('Authorization',''), 'Bearer '+token):
                self.send_json(403, {'error':{'message':'Gateway request not authorized'}}); return
            length = int(self.headers.get('Content-Length',0))
            if not 0 < length < 4_000_000:
                self.send_json(400, {'error':{'message':'Invalid request length'}}); return
            payload = json.loads(self.rfile.read(length))
            model = payload.get('model')
            if model not in {'glm-5.3','glm-5.3-flash'} or payload.get('stream'):
                self.send_json(400, {'error':{'message':'Unsupported model or streaming request'}}); return
            if payload.get('max_tokens',0) > 8192:
                self.send_json(400, {'error':{'message':'Output tokens exceed the declared pilot protocol'}}); return
            with gate:
                time.sleep(max(0, 1 - (time.monotonic() - last_start[0])))
                last_start[0] = time.monotonic()
                started = time.perf_counter()
                try:
                    remote = client.post(endpoint, headers={'Authorization':'Bearer '+key}, json=payload)
                    body = remote.json(); status = remote.status_code
                    record = clean({'at':datetime.now(timezone.utc).isoformat(), 'requested_model':model,
                                    'returned_model':body.get('model'), 'status':status,
                                    'latency_ms':(time.perf_counter()-started)*1000,
                                    'request':payload, 'response':body})
                    with args.log.open('a') as log:
                        log.write(json.dumps(record)+'\n'); log.flush()
                    if remote.is_success and body.get('model') != model:
                        self.send_json(409, {'error':{'message':'Returned model identity differs from requested model'}}); return
                    self.send_json(status, clean(body))
                except (httpx.HTTPError, ValueError) as exc:
                    self.send_json(502, {'error':{'message':type(exc).__name__}})

    server = ThreadingHTTPServer(('127.0.0.1',8769),Handler)
    thread = threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    env = dict(os.environ); env.pop('ZAI_API_KEY',None)
    env['OPENAI_API_KEY'] = token
    env['LITELLM_LOG'] = 'ERROR'
    cmd = [args.harbor, 'jobs', 'resume', '--job-path', str(args.resume)] if args.resume else [args.harbor,'run','-c',str(args.config)]
    try:
        result = subprocess.run(cmd,env=env)
    finally:
        server.shutdown(); server.server_close(); client.close()
    raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()

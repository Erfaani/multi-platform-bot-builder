"""Webhook-ingress load test (Phase 10 exit criterion: "load test at target bot count").

Target (docs/00-ANALYSIS.md R-04, at the doc's 1,000-bot reference scale): "receive
webhook, validate, persist InboundUpdate, and enqueue — target p99 under 50 ms so the
platform never retries us."

What this measures: HTTP response latency for `POST /webhooks/telegram/<instance>/`
against a real running server and a real Redis broker (`apply_async` genuinely publishes
over the network — this script does not run with `CELERY_TASK_ALWAYS_EAGER`, which would
measure full synchronous message processing instead of the ingress-and-enqueue path the
target is actually about).

Usage — run against any already-running backend, e.g. the docker compose `backend`
service, or a local `waitress`/`gunicorn` instance:

    python scripts/load_test_webhook.py \\
        --url http://localhost:8000/webhooks/telegram/<instance-public-id>/ \\
        --secret <the instance's webhook secret> \\
        --requests 1000 --concurrency 20

There is no seeding built in here on purpose — point it at a real instance + webhook
secret already in your target database (see DEPLOYMENT.md's load-test section for how the
Phase 10 numbers here were produced, including the throwaway-database seeding used).
"""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor

import httpx


def run(url: str, secret: str, request_count: int, concurrency: int) -> None:
    headers = {"X-Telegram-Bot-Api-Secret-Token": secret, "Content-Type": "application/json"}
    # trust_env=False: httpx's default environment/proxy autodetection is measurably slow
    # per Client() on Windows — irrelevant to what this measures, so it's disabled rather
    # than accidentally becoming part of the number.
    client = httpx.Client(
        timeout=10, trust_env=False,
        limits=httpx.Limits(max_connections=concurrency * 2, max_keepalive_connections=concurrency * 2),
    )

    def one(update_id: int) -> tuple[float, int]:
        payload = {
            "update_id": update_id,
            "message": {
                "message_id": update_id,
                "chat": {"id": 900_000_000 + update_id},
                "from": {"id": 900_000_000 + update_id},
                "text": "/start",
            },
        }
        started = time.perf_counter()
        response = client.post(url, content=json.dumps(payload), headers=headers)
        return time.perf_counter() - started, response.status_code

    # Warm every worker thread's DB/broker connections first. A cold Postgres backend
    # fork per new connection is a real, one-time cost a long-running production process
    # pays once, not per request — measuring it inside the timed run conflates the two
    # and was the single biggest source of noise while developing this script.
    print(f"warming up {concurrency} server worker connections...")
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        list(pool.map(one, range(-concurrency, 0)))

    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        results = list(pool.map(one, range(request_count)))
    elapsed = time.perf_counter() - start

    latencies = sorted(r[0] for r in results)
    statuses = [r[1] for r in results]
    bad = [s for s in statuses if s != 200]
    n = len(latencies)

    print(f"requests: {n}  concurrency: {concurrency}  wall clock: {elapsed:.2f}s")
    print(f"throughput: {n / elapsed:.1f} req/s")
    print(f"non-200 responses: {len(bad)} {sorted(set(bad))}")
    print(
        f"p50: {latencies[n // 2] * 1000:.1f}ms  "
        f"p95: {latencies[int(n * 0.95)] * 1000:.1f}ms  "
        f"p99: {latencies[int(n * 0.99)] * 1000:.1f}ms  "
        f"max: {latencies[-1] * 1000:.1f}ms"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Full webhook URL for one instance")
    parser.add_argument("--secret", required=True, help="That instance's active webhook secret")
    parser.add_argument("--requests", type=int, default=1000)
    parser.add_argument("--concurrency", type=int, default=20)
    args = parser.parse_args()
    run(args.url, args.secret, args.requests, args.concurrency)

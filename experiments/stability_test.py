"""
Day 30 — Stability Test for the local LLM service.

Sends N concurrent requests to the /stream SSE endpoint and measures:
  - time to first token (TTFT)
  - total request duration
  - success / error / timeout counts
  - throughput (requests per second)

Usage:
  # Start the service first:
  python3 -m deepseek_chat.web.app

  # Run stability test (default: 5 concurrent, 10 total requests):
  python3 experiments/stability_test.py

  # Custom params:
  python3 experiments/stability_test.py --url http://127.0.0.1:8000 \
      --concurrency 3 --requests 9 --api-key your-key
"""
from __future__ import annotations

import argparse
import asyncio
import statistics
import time
from dataclasses import dataclass
from typing import List, Optional

import aiohttp

# Short questions — we want to test throughput, not model quality
TEST_QUESTIONS = [
    "What is 2+2?",
    "Name three programming languages.",
    "What color is the sky?",
    "How many days are in a week?",
    "What is Python?",
    "Define REST API in one sentence.",
    "What does CPU stand for?",
    "Name one sorting algorithm.",
    "What is HTTP?",
    "What is a variable in programming?",
]


@dataclass
class RequestResult:
    question: str
    success: bool
    ttft_s: Optional[float]   # time to first token
    total_s: Optional[float]  # total duration
    tokens_received: int
    error: Optional[str]
    status_code: Optional[int]


async def _send_request(
    session: aiohttp.ClientSession,
    base_url: str,
    question: str,
    api_key: Optional[str],
    timeout_s: float,
    semaphore: asyncio.Semaphore,
) -> RequestResult:
    url = f"{base_url}/stream"
    params = {"message": question, "session_id": f"stability_{id(question)}"}
    headers = {}
    if api_key:
        headers["X-API-Key"] = api_key

    t_start = time.perf_counter()
    ttft: Optional[float] = None
    tokens = 0
    error_msg: Optional[str] = None
    status: Optional[int] = None

    async with semaphore:
        try:
            async with session.get(
                url, params=params, headers=headers,
                timeout=aiohttp.ClientTimeout(total=timeout_s),
            ) as resp:
                status = resp.status
                if resp.status != 200:
                    body = await resp.text()
                    return RequestResult(
                        question=question, success=False,
                        ttft_s=None, total_s=round(time.perf_counter() - t_start, 3),
                        tokens_received=0, error=f"HTTP {resp.status}: {body[:120]}",
                        status_code=status,
                    )

                async for raw_line in resp.content:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data in ("[DONE]", ""):
                        continue
                    # Skip JSON metadata chunks (tool calls, usage stats)
                    if data.startswith('{"__type__"'):
                        continue
                    if ttft is None:
                        ttft = round(time.perf_counter() - t_start, 3)
                    tokens += len(data)

        except asyncio.TimeoutError:
            error_msg = f"Timeout after {timeout_s:.0f}s"
        except aiohttp.ClientConnectorError as e:
            error_msg = f"Connection error: {e}"
        except Exception as e:
            error_msg = str(e)

    total = round(time.perf_counter() - t_start, 3)
    return RequestResult(
        question=question,
        success=error_msg is None and (status or 0) < 400,
        ttft_s=ttft,
        total_s=total,
        tokens_received=tokens,
        error=error_msg,
        status_code=status,
    )


async def run_stability_test(
    base_url: str = "http://127.0.0.1:8000",
    concurrency: int = 5,
    n_requests: int = 10,
    api_key: Optional[str] = None,
    timeout_s: float = 60.0,
    verbose: bool = True,
) -> List[RequestResult]:
    questions = [TEST_QUESTIONS[i % len(TEST_QUESTIONS)] for i in range(n_requests)]
    semaphore = asyncio.Semaphore(concurrency)

    if verbose:
        print(f"\n{'='*60}")
        print("  DAY 30 — STABILITY TEST")
        print(f"{'='*60}")
        print(f"  URL         : {base_url}")
        print(f"  Concurrency : {concurrency} parallel requests")
        print(f"  Total reqs  : {n_requests}")
        print(f"  Auth        : {'enabled' if api_key else 'disabled'}")
        print(f"  Timeout     : {timeout_s:.0f}s per request")
        print(f"{'='*60}\n")

    connector = aiohttp.TCPConnector(limit=concurrency + 5)
    t_wall_start = time.perf_counter()

    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [
            _send_request(session, base_url, q, api_key, timeout_s, semaphore)
            for q in questions
        ]
        results: List[RequestResult] = []
        completed = 0
        for coro in asyncio.as_completed(tasks):
            r = await coro
            results.append(r)
            completed += 1
            if verbose:
                status_str = "OK " if r.success else "ERR"
                ttft_str = f"TTFT={r.ttft_s:.2f}s" if r.ttft_s else "TTFT=n/a "
                total_str = f"total={r.total_s:.2f}s" if r.total_s else ""
                err_str = f"  ← {r.error}" if r.error else ""
                q_short = r.question[:40]
                print(f"  [{completed:2}/{n_requests}] {status_str}  {ttft_str}  {total_str}  {q_short!r}{err_str}")

    wall_elapsed = round(time.perf_counter() - t_wall_start, 2)

    # Summary
    ok = [r for r in results if r.success]
    fail = [r for r in results if not r.success]
    ttfts = [r.ttft_s for r in ok if r.ttft_s is not None]
    totals = [r.total_s for r in ok if r.total_s is not None]

    if verbose:
        print(f"\n{'='*60}")
        print("  SUMMARY")
        print(f"{'='*60}")
        print(f"  Requests    : {n_requests}  (concurrency={concurrency})")
        print(f"  Success     : {len(ok)}  ({round(100*len(ok)/n_requests)}%)")
        print(f"  Failures    : {len(fail)}")
        if ttfts:
            print(f"  TTFT        : avg={statistics.mean(ttfts):.2f}s  "
                  f"p50={statistics.median(ttfts):.2f}s  "
                  f"min={min(ttfts):.2f}s  max={max(ttfts):.2f}s")
        if totals:
            print(f"  Total time  : avg={statistics.mean(totals):.2f}s  "
                  f"p50={statistics.median(totals):.2f}s  "
                  f"min={min(totals):.2f}s  max={max(totals):.2f}s")
        print(f"  Wall time   : {wall_elapsed}s")
        print(f"  Throughput  : {round(len(ok)/wall_elapsed, 2)} req/s")
        if fail:
            print(f"\n  Errors:")
            for r in fail:
                print(f"    - {r.question[:40]!r}: {r.error}")
        print(f"{'='*60}\n")

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Day 30 — stability test for local LLM service")
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="Service base URL")
    parser.add_argument("--concurrency", "-c", type=int, default=5,
                        help="Max parallel requests (default: 5)")
    parser.add_argument("--requests", "-n", type=int, default=10,
                        help="Total requests to send (default: 10)")
    parser.add_argument("--api-key", default=None, help="X-API-Key value (if auth is enabled)")
    parser.add_argument("--timeout", type=float, default=60.0,
                        help="Timeout per request in seconds (default: 60)")
    args = parser.parse_args()

    asyncio.run(run_stability_test(
        base_url=args.url,
        concurrency=args.concurrency,
        n_requests=args.requests,
        api_key=args.api_key,
        timeout_s=args.timeout,
        verbose=True,
    ))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# infra/load_test_native.py
"""Zero-dependency concurrent load tester for Day 10 API verification.

Uses only Python standard library (urllib, concurrent.futures, statistics).
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import random
import statistics
import sys
import time
import urllib.error
import urllib.request

CLINICAL_PROMPTS = [
    "What are the inclusion criteria for adult oncology patients?",
    "What are the primary endpoints and overall response rates?",
    "List common exclusion criteria for patients with prior cardiac history.",
    "What is the dosing schedule and administration regimen?",
    "What adverse events or toxicity thresholds are documented in phase 2?",
]


def send_request(target_url: str, vu_id: int) -> dict:
  """Sends a single HTTP POST request to /search and measures latency."""
  query = random.choice(CLINICAL_PROMPTS)
  payload = json.dumps({
      "query": query,
      "top_k": 3,
      "session_id": f"native-vu-session-{vu_id}",
  }).encode("utf-8")

  req = urllib.request.Request(
      url=target_url,
      data=payload,
      headers={
          "Content-Type": "application/json",
          "User-Agent": "native-python-load-tester/1.0",
      },
      method="POST",
  )

  start_time = time.perf_counter()
  try:
    with urllib.request.urlopen(req, timeout=15) as resp:
      latency_ms = (time.perf_counter() - start_time) * 1000.0
      status_code = resp.getcode()
      body = json.loads(resp.read().decode("utf-8"))
      results = body.get("results", [])
      has_valid_results = len(results) > 0 and "cosine_similarity" in results[0]

      return {
          "success": status_code == 200 and has_valid_results,
          "status_code": status_code,
          "latency_ms": latency_ms,
          "error": None,
      }
  except urllib.error.HTTPError as e:
    latency_ms = (time.perf_counter() - start_time) * 1000.0
    return {
        "success": False,
        "status_code": e.code,
        "latency_ms": latency_ms,
        "error": f"HTTPError {e.code}",
    }
  except Exception as e:
    latency_ms = (time.perf_counter() - start_time) * 1000.0
    return {
        "success": False,
        "status_code": 0,
        "latency_ms": latency_ms,
        "error": str(e),
    }


def compute_percentile(sorted_list: list, percentile: float) -> float:
  """Calculates percentile from a sorted list of numbers."""
  if not sorted_list:
    return 0.0
  idx = int(len(sorted_list) * (percentile / 100.0))
  idx = min(idx, len(sorted_list) - 1)
  return sorted_list[idx]


def run_load_test(
    target_url: str, total_requests: int, concurrency: int
) -> None:
  print("=" * 65)
  print("🚀 Starting Zero-Dependency Concurrent Load Test")
  print(f"   Target URL:     {target_url}")
  print(f"   Total Requests: {total_requests}")
  print(f"   Concurrency:    {concurrency} workers")
  print("=" * 65)

  # Normalise URL
  if not target_url.endswith("/search"):
    target_url = target_url.rstrip("/") + "/search"

  results = []
  wall_clock_start = time.perf_counter()

  with ThreadPoolExecutor(max_workers=concurrency) as executor:
    futures = [
        executor.submit(send_request, target_url, i % concurrency)
        for i in range(total_requests)
    ]
    for future in as_completed(futures):
      results.append(future.result())

  total_wall_time = time.perf_counter() - wall_clock_start

  # Aggregate metrics
  successes = [r for r in results if r["success"]]
  failures = [r for r in results if not r["success"]]
  latencies = sorted([r["latency_ms"] for r in results])

  avg_latency = statistics.mean(latencies) if latencies else 0.0
  min_latency = latencies[0] if latencies else 0.0
  max_latency = latencies[-1] if latencies else 0.0
  p50 = compute_percentile(latencies, 50)
  p90 = compute_percentile(latencies, 90)
  p95 = compute_percentile(latencies, 95)
  p99 = compute_percentile(latencies, 99)
  rps = len(results) / total_wall_time if total_wall_time > 0 else 0.0

  print("\n" + "=" * 65)
  print("📊 Load Test Results Summary")
  print("=" * 65)
  print(f"Total Requests:      {len(results)}")
  print(
      f"Successful (200 OK): {len(successes)} ({len(successes)/len(results)*100:.1f}%)"
  )
  print(f"Failed:              {len(failures)}")
  print(f"Total Duration:      {total_wall_time:.2f} s")
  print(f"Throughput:          {rps:.2f} req/s")
  print("-" * 65)
  print("Latency Distribution (ms):")
  print(f"  Min:               {min_latency:.2f} ms")
  print(f"  Avg:               {avg_latency:.2f} ms")
  print(f"  Median (p50):      {p50:.2f} ms")
  print(f"  p90:               {p90:.2f} ms")
  print(f"  p95:               {p95:.2f} ms")
  print(f"  p99:               {p99:.2f} ms")
  print(f"  Max:               {max_latency:.2f} ms")
  print("=" * 65)

  if failures:
    print("\n⚠️ Failure Details:")
    error_counts = {}
    for f in failures:
      err = f["error"] or f"Status {f['status_code']}"
      error_counts[err] = error_counts.get(err, 0) + 1
    for err, cnt in error_counts.items():
      print(f"  - {err}: {cnt} occurrences")
    sys.exit(1)


if __name__ == "__main__":
  parser = argparse.ArgumentParser(
      description="Run concurrent load testing on /search endpoint."
  )
  parser.add_argument(
      "url",
      nargs="?",
      default="http://localhost:8080/search",
      help="Target base URL or /search URL",
  )
  parser.add_argument(
      "-n",
      "--requests",
      type=int,
      default=50,
      help="Total number of requests (default: 50)",
  )
  parser.add_argument(
      "-c",
      "--concurrency",
      type=int,
      default=5,
      help="Number of concurrent workers (default: 5)",
  )
  args = parser.parse_args()

  run_load_test(args.url, args.requests, args.concurrency)

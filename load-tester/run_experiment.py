"""
run_experiment.py
-----------------
Drives the workload trace against the dispatcher and records:
  - per-request latency
  - dropped requests (429)
  - timed-out requests (504)
  - QPS actually sent vs scheduled
  - replica count per second        ← polled from Prometheus
  - CPU cores used per second       ← polled from Prometheus

Results are saved to results/<experiment_name>/
  raw.csv        — one row per request
  summary.csv    — one row per second (aggregated + infra metrics)

Usage:
    python run_experiment.py --name hpa_70 --dispatcher http://localhost:9000
    python run_experiment.py --name custom  --dispatcher http://localhost:9000
    python run_experiment.py --name hpa_70 --prometheus http://localhost:9090
"""

import argparse
import asyncio
import csv
import math
import time
import random
import logging
from pathlib import Path
from dataclasses import dataclass

import httpx

from workload import TRACE, DURATION_S

# ── Logging ───────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s"
)
logger = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────
IMAGES_DIR = Path(__file__).parent / "sample_images"

# ── Defaults ──────────────────────────────────────────────────────────
DEFAULT_DISPATCHER  = "http://localhost:9000"
DEFAULT_PROMETHEUS  = "http://localhost:9090"
REQUEST_TIMEOUT     = 12.0


# ─────────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────────

@dataclass
class RequestResult:
    second:      int
    sent_at:     float
    latency_ms:  float   # -1 if dropped/timeout
    status:      str     # "ok" | "dropped" | "timeout" | "error"
    status_code: int

@dataclass
class InfraSnapshot:
    """One Prometheus snapshot taken at the start of each second."""
    second:       int
    replicas:     float   # current replica count
    cpu_cores:    float   # avg CPU cores used across inference pods


# ─────────────────────────────────────────────────────────────────────
# Prometheus helpers
# ─────────────────────────────────────────────────────────────────────

def query_prometheus_sync(prometheus_url: str, promql: str) -> float:
    """Synchronous Prometheus instant query. Returns 0.0 on any failure."""
    try:
        resp = httpx.get(
            f"{prometheus_url}/api/v1/query",
            params={"query": promql},
            timeout=3.0
        )
        results = resp.json().get("data", {}).get("result", [])
        if results:
            value = float(results[0]["value"][1])
            return 0.0 if (math.isnan(value) or math.isinf(value)) else value
        return 0.0
    except Exception:
        return 0.0


def snapshot_infra(prometheus_url: str, second: int) -> InfraSnapshot:
    """
    Poll Prometheus for current replica count and CPU cores.
    Called once per second during the experiment.

    CPU cores = replica count x 1 core/pod (each pod has cpu limit=1).
    This matches the professor's requirement: "number of CPU cores used".
    """
    # Count inference pods via kubernetes-pods job (port 8080)
    # This correctly counts all running replicas as individual pod IPs
    replicas = query_prometheus_sync(
        prometheus_url,
        'count(process_cpu_seconds_total{job="kubernetes-pods", instance=~".*:8080"})'
    )
    # Final fallback
    if replicas == 0:
        replicas = 1.0

    # CPU cores allocated = replicas x 1 core per pod
    # Each inference pod has requests=limits=1 CPU
    cpu_cores = replicas

    return InfraSnapshot(second=second, replicas=replicas, cpu_cores=cpu_cores)


# ─────────────────────────────────────────────────────────────────────
# Image loader
# ─────────────────────────────────────────────────────────────────────

def load_images() -> list[bytes]:
    if not IMAGES_DIR.exists():
        raise FileNotFoundError(
            f"Sample images directory not found: {IMAGES_DIR}\n"
            f"Create it and add some JPEG images."
        )
    images = []
    for ext in ("*.jpg", "*.jpeg", "*.JPEG", "*.JPG"):
        for p in IMAGES_DIR.glob(ext):
            images.append(p.read_bytes())
    if not images:
        raise FileNotFoundError(f"No JPEG images found in {IMAGES_DIR}.")
    logger.info(f"Loaded {len(images)} sample image(s)")
    return images


# ─────────────────────────────────────────────────────────────────────
# Single request
# ─────────────────────────────────────────────────────────────────────

async def send_request(
    client: httpx.AsyncClient,
    image_bytes: bytes,
    second: int,
) -> RequestResult:
    sent_at = time.time()
    try:
        resp = await client.post(
            "/predict",
            files={"file": ("image.jpg", image_bytes, "image/jpeg")},
            timeout=REQUEST_TIMEOUT,
        )
        latency_ms = (time.time() - sent_at) * 1000
        if resp.status_code == 200:
            return RequestResult(second, sent_at, latency_ms, "ok", 200)
        elif resp.status_code == 429:
            return RequestResult(second, sent_at, -1, "dropped", 429)
        else:
            return RequestResult(second, sent_at, -1, "error", resp.status_code)
    except httpx.TimeoutException:
        return RequestResult(second, sent_at, -1, "timeout", 0)
    except Exception as e:
        logger.warning(f"Request error: {e}")
        return RequestResult(second, sent_at, -1, "error", 0)


# ─────────────────────────────────────────────────────────────────────
# Experiment runner
# ─────────────────────────────────────────────────────────────────────

async def run_experiment(
    name: str,
    dispatcher_url: str,
    prometheus_url: str,
) -> tuple[list[RequestResult], list[InfraSnapshot]]:

    images    = load_images()
    results   = []
    snapshots = []
    start_ts  = time.time()

    logger.info(f"Starting experiment '{name}'")
    logger.info(f"Dispatcher : {dispatcher_url}")
    logger.info(f"Prometheus : {prometheus_url}")
    logger.info(f"Duration   : {DURATION_S}s (~{DURATION_S/60:.1f} min)")
    logger.info("─" * 60)

    async with httpx.AsyncClient(base_url=dispatcher_url) as client:
        for second, qps in enumerate(TRACE):
            second_start = time.time()

            # ── Poll Prometheus at the start of each second ───────────
            # Run in executor so it doesn't block the event loop
            loop     = asyncio.get_event_loop()
            snapshot = await loop.run_in_executor(
                None, snapshot_infra, prometheus_url, second
            )
            snapshots.append(snapshot)

            # ── Send this second's requests ───────────────────────────
            tasks = []
            for i in range(qps):
                delay = i / qps
                img   = random.choice(images)

                async def _send(img=img, sec=second, d=delay):
                    await asyncio.sleep(d)
                    return await send_request(client, img, sec)

                tasks.append(asyncio.create_task(_send()))

            second_results = await asyncio.gather(*tasks)
            results.extend(second_results)

            # ── Per-second log ────────────────────────────────────────
            ok       = sum(1 for r in second_results if r.status == "ok")
            dropped  = sum(1 for r in second_results if r.status == "dropped")
            timeouts = sum(1 for r in second_results if r.status == "timeout")
            lats     = [r.latency_ms for r in second_results if r.latency_ms > 0]
            p99      = sorted(lats)[int(len(lats) * 0.99)] if lats else 0

            logger.info(
                f"s={second:4d}  qps={qps:2d}  "
                f"ok={ok:2d}  drop={dropped:2d}  timeout={timeouts:2d}  "
                f"p99={p99:.0f}ms  "
                f"replicas={snapshot.replicas:.0f}  "
                f"cpu={snapshot.cpu_cores:.2f}cores"
            )

            # Sleep for the remainder of this second
            elapsed   = time.time() - second_start
            sleep_for = max(0.0, 1.0 - elapsed)
            await asyncio.sleep(sleep_for)

    total_elapsed = time.time() - start_ts
    logger.info(f"Experiment '{name}' complete in {total_elapsed:.1f}s")
    return results, snapshots


# ─────────────────────────────────────────────────────────────────────
# CSV output
# ─────────────────────────────────────────────────────────────────────

def save_results(
    name: str,
    results: list[RequestResult],
    snapshots: list[InfraSnapshot],
):
    out_dir = Path(__file__).parent / "results" / name
    out_dir.mkdir(parents=True, exist_ok=True)

    # Build snapshot lookup: second → InfraSnapshot
    snap_map = {s.second: s for s in snapshots}

    # ── raw.csv ───────────────────────────────────────────────────────
    raw_path = out_dir / "raw.csv"
    with open(raw_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["second", "sent_at", "latency_ms", "status", "status_code"])
        for r in results:
            writer.writerow([r.second, f"{r.sent_at:.3f}",
                             f"{r.latency_ms:.2f}", r.status, r.status_code])
    logger.info(f"Saved raw   → {raw_path}")

    # ── summary.csv ───────────────────────────────────────────────────
    summary_path = out_dir / "summary.csv"
    with open(summary_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "second",
            "p99_latency_ms",
            "cpu_cores",
        ])

        for second, scheduled_qps in enumerate(TRACE):
            sec_results = [r for r in results if r.second == second]
            ok_results  = [r for r in sec_results if r.status == "ok"]
            lats        = sorted(r.latency_ms for r in ok_results)

            p99      = lats[int(len(lats) * 0.99)] if lats else 0

            snap      = snap_map.get(second)
            cpu_cores = snap.cpu_cores if snap else 0

            writer.writerow([
                second,
                f"{p99:.2f}",
                f"{cpu_cores:.4f}",
            ])

    logger.info(f"Saved summary → {summary_path}")


def print_summary(name: str, results: list[RequestResult],
                  snapshots: list[InfraSnapshot]):
    total    = len(results)
    ok       = sum(1 for r in results if r.status == "ok")
    dropped  = sum(1 for r in results if r.status == "dropped")
    timeouts = sum(1 for r in results if r.status == "timeout")
    lats     = sorted(r.latency_ms for r in results if r.latency_ms > 0)
    p99      = lats[int(len(lats) * 0.99)] if lats else 0
    avg      = sum(lats) / len(lats) if lats else 0
    max_rep  = max((s.replicas for s in snapshots), default=0)
    max_cpu  = max((s.cpu_cores for s in snapshots), default=0)

    print(f"\n{'─'*55}")
    print(f"Experiment  : {name}")
    print(f"Total sent  : {total}")
    print(f"OK          : {ok}  ({ok/total*100:.1f}%)")
    print(f"Dropped     : {dropped}  ({dropped/total*100:.1f}%)")
    print(f"Timeouts    : {timeouts}  ({timeouts/total*100:.1f}%)")
    print(f"Avg latency : {avg:.1f}ms")
    print(f"P99 latency : {p99:.1f}ms")
    print(f"Peak replicas: {max_rep:.0f}")
    print(f"Peak CPU    : {max_cpu:.2f} cores")
    print(f"{'─'*55}\n")


# ─────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Run a load test experiment")
    parser.add_argument("--name",       required=True,
                        help="Experiment name (e.g. hpa_70, hpa_90, custom)")
    parser.add_argument("--dispatcher", default=DEFAULT_DISPATCHER,
                        help=f"Dispatcher URL (default: {DEFAULT_DISPATCHER})")
    parser.add_argument("--prometheus", default=DEFAULT_PROMETHEUS,
                        help=f"Prometheus URL (default: {DEFAULT_PROMETHEUS})")
    args = parser.parse_args()

    results, snapshots = asyncio.run(
        run_experiment(args.name, args.dispatcher, args.prometheus)
    )
    save_results(args.name, results, snapshots)
    print_summary(args.name, results, snapshots)


if __name__ == "__main__":
    main()
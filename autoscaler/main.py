import os
import time
import math
import logging
import collections
import httpx
from kubernetes import client, config

# Configure a root logger for logging system
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s"
)
logger = logging.getLogger(__name__)

# Configuration (override via environment variables)
PROMETHEUS_URL   = os.getenv("PROMETHEUS_URL",  "http://localhost:9090")
DISPATCHER_URL   = os.getenv("DISPATCHER_URL",  "http://localhost:9000")
DEPLOYMENT_NAME  = os.getenv("DEPLOYMENT_NAME", "inference-deployment")
NAMESPACE        = os.getenv("NAMESPACE",        "default")

CHECK_INTERVAL_S = int(float(os.getenv("CHECK_INTERVAL",  "10")))
MIN_REPLICAS     = int(os.getenv("MIN_REPLICAS", "1"))
MAX_REPLICAS     = int(os.getenv("MAX_REPLICAS", "8"))

# Thresholds
LATENCY_SLO_S          = float(os.getenv("LATENCY_SLO",          "0.4"))   # p99 target
LATENCY_EMERGENCY_S    = float(os.getenv("LATENCY_EMERGENCY",     "0.6"))   # hard breach
QUEUE_SCALE_UP         = int(os.getenv("QUEUE_SCALE_UP",          "5"))     # queue length that triggers +1
QUEUE_EMERGENCY        = int(os.getenv("QUEUE_EMERGENCY",         "30"))    # queue length that triggers fast scale
CPU_HIGH_FRACTION      = float(os.getenv("CPU_HIGH_FRACTION",     "0.75"))  # CPU safety net

# Cooldowns (asymmetric: fast up, slow down)
SCALE_UP_COOLDOWN_S    = int(os.getenv("SCALE_UP_COOLDOWN",   "0"))
SCALE_DOWN_COOLDOWN_S  = int(os.getenv("SCALE_DOWN_COOLDOWN", "60"))

# How many rate samples to keep for trend detection
RATE_WINDOW = 3

# Initialise the timestamps for scale events
last_scale_up_time   = 0.0
last_scale_down_time = 0.0

# Sliding window of (timestamp, request_rate) for trend detection
rate_history: collections.deque = collections.deque(maxlen=RATE_WINDOW)

# Run a PromQL instant query and return the first scalar result.
def query_prometheus(promql: str) -> float | None:
    try:
        resp = httpx.get(
            f"{PROMETHEUS_URL}/api/v1/query",
            params={"query": promql},
            timeout=5.0
        )
        results = resp.json().get("data", {}).get("result", [])
        if results:
            value = float(results[0]["value"][1])
            return None if math.isnan(value) or math.isinf(value) else value
        return None
    except Exception as e:
        logger.warning(f"Prometheus query failed [{promql[:60]}]: {e}")
        return None

# Fetches metrics for the autoscaler
def get_metrics() -> dict:
    # Queue length — direct gauge from dispatcher
    queue_len = query_prometheus('dispatcher_queue_length{job="dispatcher"}')

    # p99 end-to-end latency over last 1 minute
    latency_p99 = query_prometheus(
        'histogram_quantile(0.99, '
        'rate(dispatcher_latency_seconds_bucket{job="dispatcher"}[1m]))'
    )
    # Reject clearly stale or impossible readings
    if latency_p99 is not None and (latency_p99 < 0 or latency_p99 > 10):
        logger.warning(f"Discarding unrealistic p99={latency_p99:.3f}s")
        latency_p99 = None

    # CPU utilisation per inference pod (fraction of 1 CPU core)
    # Uses process_cpu_seconds_total exposed by the FastAPI app directly
    # avg() across all inference pods gives per-replica utilisation
    cpu_util = query_prometheus(
    'avg(rate(process_cpu_seconds_total{job="kubernetes-pods", instance=~".*:8080"}[1m]))'
    )

    # Request rate (requests/second) into dispatcher
    request_rate = query_prometheus(
        'rate(dispatcher_requests_total{job="dispatcher"}[1m])'
    )

    return {
        "queue_len":    queue_len,
        "latency_p99":  latency_p99,
        "cpu_util":     cpu_util,
        "request_rate": request_rate,
    }


# Estimate how fast the request rate is changing
def compute_rate_slope() -> float | None:
    if len(rate_history) < 2:
        return None

    # Simple finite difference across the window
    times  = [h[0] for h in rate_history]
    rates  = [h[1] for h in rate_history]
    dt     = times[-1] - times[0]
    if dt <= 0:
        return None
    slope = (rates[-1] - rates[0]) / dt   # Δ(req/s) / Δs
    return slope
# Get current replica count
def get_current_replicas(apps_v1) -> int:
    dep = apps_v1.read_namespaced_deployment(DEPLOYMENT_NAME, NAMESPACE)
    return dep.spec.replicas or 1

# Set the desired replica count
def set_replicas(apps_v1, n: int):
    apps_v1.patch_namespaced_deployment(
        DEPLOYMENT_NAME, NAMESPACE,
        {"spec": {"replicas": n}}
    )
    logger.info(f"★  Kubernetes deployment patched → {n} replicas")

# Notify the dispatcher about the updated replica count
def notify_dispatcher(n: int):
    """Tell dispatcher to match its worker pool to the new replica count."""
    try:
        resp = httpx.post(
            f"{DISPATCHER_URL}/scale",
            params={"replicas": n},
            timeout=5.0
        )
        logger.info(f"Dispatcher notified: {resp.json()}")
    except Exception as e:
        logger.warning(f"Could not notify dispatcher: {e}")

# Evaluate all signals and return the desired replica count
def compute_desired_replicas(current: int, m: dict) -> tuple[int, str]:
    """
    Three-tier decision.
    Returns (desired_replicas, reason_string).
    """
    global last_scale_up_time, last_scale_down_time

    now          = time.time()
    queue_len    = m["queue_len"]    or 0.0
    latency_p99  = m["latency_p99"]
    cpu_util     = m["cpu_util"]     or 0.0
    request_rate = m["request_rate"] or 0.0

    # ── Update rate history for trend detection ───────────────────────
    if m["request_rate"] is not None:
        rate_history.append((now, m["request_rate"]))
    slope = compute_rate_slope()

    # Emergency Scale UP 
    if latency_p99 is not None and latency_p99 >= LATENCY_EMERGENCY_S:
        desired  = min(current + 3, MAX_REPLICAS)
        reason   = (f"EMERGENCY: p99={latency_p99:.3f}s ≥ {LATENCY_EMERGENCY_S}s "
                    f"→ +3 replicas")
        last_scale_up_time = now
        return desired, reason

    if queue_len >= QUEUE_EMERGENCY:
        desired  = min(current + 2, MAX_REPLICAS)
        reason   = (f"EMERGENCY: queue={queue_len:.0f} ≥ {QUEUE_EMERGENCY} "
                    f"→ +2 replicas")
        last_scale_up_time = now
        return desired, reason

    # Proactive scale up
    up_ready = (now - last_scale_up_time) >= SCALE_UP_COOLDOWN_S

    proactive_triggers = []

    if latency_p99 is not None and latency_p99 >= LATENCY_SLO_S:
        proactive_triggers.append(f"p99={latency_p99:.3f}s ≥ SLO={LATENCY_SLO_S}s")

    if queue_len >= QUEUE_SCALE_UP:
        proactive_triggers.append(f"queue={queue_len:.0f} ≥ {QUEUE_SCALE_UP}")

    # Rate trend: slope > 0.05 req/s² means load is visibly accelerating
    if slope is not None and slope > 0.05:
        proactive_triggers.append(f"rate slope=+{slope:.3f} req/s² (rising)")

    # CPU safety net: if CPU is high but other signals are quiet
    if cpu_util >= CPU_HIGH_FRACTION:
        proactive_triggers.append(f"cpu={cpu_util:.1%} ≥ {CPU_HIGH_FRACTION:.0%}")

    if proactive_triggers and current < MAX_REPLICAS:
        if up_ready:
            desired = min(current + 1, MAX_REPLICAS)
            reason  = "PROACTIVE +1: " + ", ".join(proactive_triggers)
            last_scale_up_time = now
            return desired, reason
        else:
            wait = SCALE_UP_COOLDOWN_S - (now - last_scale_up_time)
            reason = (f"PROACTIVE triggers present but up-cooldown active "
                      f"({wait:.0f}s remaining): " + ", ".join(proactive_triggers))
            return current, reason

    # Steady State: Hold or scale down
    if current <= MIN_REPLICAS:
        return current, "STEADY: at minimum replicas"

    down_ready = (now - last_scale_down_time) >= SCALE_DOWN_COOLDOWN_S

    # Check every gate
    gates = {
        "queue empty":      queue_len < QUEUE_SCALE_DOWN_THRESHOLD,
        "latency OK":       (latency_p99 is None or
                             latency_p99 < LATENCY_SLO_S * 0.7),
        "rate not rising":  (slope is None or slope <= 0.0),
        "cpu OK":           cpu_util < CPU_HIGH_FRACTION * 0.6,
        "cooldown elapsed": down_ready,
    }

    blocked = [name for name, passed in gates.items() if not passed]

    if not blocked:
        desired = current - 1
        reason  = "SCALE DOWN -1: all gates passed"
        last_scale_down_time = now
        return desired, reason
    else:
        reason = f"STEADY: scale-down blocked by [{', '.join(blocked)}]"
        return current, reason


# Main Loop
# Needed by Tier 3 gate check — define here so it's accessible
QUEUE_SCALE_DOWN_THRESHOLD = 1  # allow scale down only when queue is nearly empty


def run():
    # Connect to Kubernetes
    try:
        config.load_incluster_config()
        logger.info("Kubernetes: using in-cluster config")
    except config.ConfigException:
        config.load_kube_config()
        logger.info("Kubernetes: using local kubeconfig")

    apps_v1 = client.AppsV1Api()

    logger.info(
        f"Autoscaler started  "
        f"min={MIN_REPLICAS}  max={MAX_REPLICAS}  "
        f"interval={CHECK_INTERVAL_S}s  "
        f"SLO={LATENCY_SLO_S}s"
    )

    while True:
        loop_start = time.time()

        try:
            current = get_current_replicas(apps_v1)
            metrics = get_metrics()

            logger.info(
                f"Metrics → "
                f"replicas={current}  "
                f"queue={metrics['queue_len']}  "
                f"p99={metrics['latency_p99']}s  "
                f"cpu={metrics['cpu_util']}  "
                f"rate={metrics['request_rate']} req/s"
            )

            desired, reason = compute_desired_replicas(current, metrics)

            logger.info(f"Decision: {reason}")

            if desired != current:
                logger.info(f"Scaling {current} → {desired}")
                set_replicas(apps_v1, desired)
                notify_dispatcher(desired)
            else:
                logger.info(f"No change — staying at {current} replicas")

        except Exception as e:
            logger.error(f"Autoscaler loop error: {e}", exc_info=True)

        # Sleep for the remainder of the interval
        elapsed = time.time() - loop_start
        sleep_for = max(0.0, CHECK_INTERVAL_S - elapsed)
        time.sleep(sleep_for)


if __name__ == "__main__":
    run()
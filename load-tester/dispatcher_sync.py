"""
dispatcher_sync.py
------------------
Watches the inference deployment replica count every 5 seconds.
When it changes, calls POST /scale on the dispatcher so worker
count always matches replica count.

Run this on your laptop alongside any experiment:
    python dispatcher_sync.py

Keep it running in a separate terminal for the full experiment duration.
Works for both HPA and custom autoscaler experiments.
"""

import time
import logging
import httpx
from kubernetes import client, config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s"
)
logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────
DISPATCHER_URL   = "http://localhost:9000"
DEPLOYMENT_NAME  = "inference-deployment"
NAMESPACE        = "default"
POLL_INTERVAL_S  = 5   # check every 5 seconds


def get_ready_replicas(apps_v1) -> int:
    """Return the number of READY inference pods."""
    dep = apps_v1.read_namespaced_deployment(DEPLOYMENT_NAME, NAMESPACE)
    # ready_replicas can be None if no pods are ready yet
    return dep.status.ready_replicas or 1


def notify_dispatcher(replicas: int):
    try:
        resp = httpx.post(
            f"{DISPATCHER_URL}/scale",
            params={"replicas": replicas},
            timeout=5.0
        )
        logger.info(f"Dispatcher synced → workers={resp.json().get('workers')}")
    except Exception as e:
        logger.warning(f"Failed to notify dispatcher: {e}")


def run():
    # Connect to Kubernetes
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()

    apps_v1      = client.AppsV1Api()
    last_replicas = 0

    logger.info(f"Dispatcher sync started — polling every {POLL_INTERVAL_S}s")

    while True:
        try:
            ready = get_ready_replicas(apps_v1)

            if ready != last_replicas:
                logger.info(f"Replica change detected: {last_replicas} → {ready}")
                notify_dispatcher(ready)
                last_replicas = ready
            else:
                logger.debug(f"No change — {ready} replicas ready")

        except Exception as e:
            logger.error(f"Sync error: {e}")

        time.sleep(POLL_INTERVAL_S)


if __name__ == "__main__":
    run()
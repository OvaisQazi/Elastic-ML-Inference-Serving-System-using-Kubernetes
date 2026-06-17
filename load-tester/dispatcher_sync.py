import time
import logging
import httpx
from kubernetes import client, config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s"
)
logger = logging.getLogger(__name__)

DISPATCHER_URL   = "http://localhost:9000"
DEPLOYMENT_NAME  = "inference-deployment"
NAMESPACE        = "default"
POLL_INTERVAL_S  = 5   # check every 5 seconds

# Return No. of ready pods
def get_ready_replicas(apps_v1) -> int:
    dep = apps_v1.read_namespaced_deployment(DEPLOYMENT_NAME, NAMESPACE)
    # ready_replicas can be None if no pods are ready yet
    return dep.status.ready_replicas or 1

# Notify the dispatcher about how many workers to use
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
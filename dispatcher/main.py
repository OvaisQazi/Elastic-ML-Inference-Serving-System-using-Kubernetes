import asyncio
import time
import httpx
import logging
from fastapi import FastAPI, File, UploadFile, HTTPException, Query
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Dispatcher")

# ── Prometheus metrics ──────────────────────────────────────────────
REQUEST_COUNT  = Counter("dispatcher_requests_total", "Total requests received")
DROPPED_COUNT  = Counter("dispatcher_requests_dropped_total", "Requests dropped")
LATENCY_HIST   = Histogram("dispatcher_latency_seconds", "End-to-end latency",
                            buckets=[0.05,0.1,0.2,0.3,0.5,0.75,1.0,2.0,5.0])
QUEUE_LENGTH   = Gauge("dispatcher_queue_length", "Current queue length")
WORKER_COUNT   = Gauge("dispatcher_worker_count", "Current number of workers")

# ── Config ──────────────────────────────────────────────────────────
INFERENCE_URL   = os.getenv("INFERENCE_URL", "http://localhost:8080")
MAX_QUEUE_SIZE  = int(os.getenv("MAX_QUEUE", "500"))
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "10.0"))
NUM_WORKERS     = int(os.getenv("NUM_WORKERS", "1"))

# ── State ────────────────────────────────────────────────────────────
queue: asyncio.Queue = None
current_workers: int = 0


# ── Worker management ────────────────────────────────────────────────

async def scale_workers(n: int):
    """
    Dynamically adjust the number of queue workers to match
    the current replica count. Called on startup and by /scale endpoint.
    Scale up: spawn new worker coroutines.
    Scale down: send poison pills so excess workers exit cleanly.
    """
    global current_workers

    if n > current_workers:
        for i in range(current_workers, n):
            asyncio.create_task(queue_worker(i))
            logger.info(f"Spawned worker {i}")

    elif n < current_workers:
        pills = current_workers - n
        logger.info(f"Sending {pills} poison pill(s) to shrink workers")
        for _ in range(pills):
            await queue.put(None)  # None = shutdown signal

    current_workers = n
    WORKER_COUNT.set(current_workers)
    logger.info(f"Worker count is now {current_workers}")


async def queue_worker(worker_id: int):
    """
    Each worker pulls one request at a time from the queue,
    forwards it to the inference service, and resolves the future.
    Exits cleanly when it receives a None (poison pill).
    """
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        while True:
            item = await queue.get()

            # Poison pill — shut this worker down
            if item is None:
                logger.info(f"Worker {worker_id} received shutdown signal")
                queue.task_done()
                return

            future, img_bytes, filename, t_arrival = item
            QUEUE_LENGTH.set(queue.qsize())

            try:
                files = {"file": (filename, img_bytes, "image/jpeg")}
                resp = await client.post(
                    f"{INFERENCE_URL}/predict",
                    files=files
                )
                resp.raise_for_status()
                result = resp.json()

                latency = time.time() - t_arrival
                LATENCY_HIST.observe(latency)
                result["total_latency_ms"] = round(latency * 1000, 2)

                if not future.done():
                    future.set_result(result)

                logger.info(
                    f"Worker {worker_id} done in {latency*1000:.1f}ms "
                    f"(queue={queue.qsize()})"
                )

            except Exception as e:
                logger.error(f"Worker {worker_id} error: {e}")
                if not future.done():
                    future.set_exception(
                        HTTPException(status_code=502, detail=str(e))
                    )
            finally:
                queue.task_done()


# ── Startup ──────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    global queue
    queue = asyncio.Queue(maxsize=MAX_QUEUE_SIZE)
    await scale_workers(NUM_WORKERS)
    logger.info(f"Dispatcher ready — inference at {INFERENCE_URL}")


# ── Endpoints ────────────────────────────────────────────────────────

@app.post("/predict")
async def dispatch(file: UploadFile = File(...)):
    """
    Receive an image request, enqueue it, wait for the worker
    to process it and return the inference result.
    """
    REQUEST_COUNT.inc()
    img_bytes = await file.read()
    t_arrival = time.time()

    if queue.full():
        DROPPED_COUNT.inc()
        raise HTTPException(status_code=429, detail="Queue full — request dropped")

    loop = asyncio.get_event_loop()
    future = loop.create_future()
    await queue.put((future, img_bytes, file.filename or "image.jpg", t_arrival))
    QUEUE_LENGTH.set(queue.qsize())

    try:
        result = await asyncio.wait_for(
            asyncio.shield(future),
            timeout=REQUEST_TIMEOUT
        )
        return JSONResponse(result)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Request timed out")


@app.post("/scale")
async def scale(replicas: int = Query(..., gt=0, le=20)):
    """
    Called by the autoscaler after it changes the Kubernetes
    replica count. Adjusts worker count to match.
    """
    logger.info(f"Scale request received: {replicas} replicas")
    await scale_workers(replicas)
    return {"workers": current_workers}


@app.get("/metrics")
def metrics():
    """Prometheus scrape endpoint."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "queue_size": queue.qsize() if queue else 0,
        "workers": current_workers
    }


@app.get("/queue_length")
def queue_length():
    return {"queue_length": queue.qsize() if queue else 0}
import asyncio
import time
import httpx
import logging
from fastapi import FastAPI, File, UploadFile, HTTPException, Query
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response
import os

# Configure a root logger for logging system
logging.basicConfig(level=logging.INFO)
# Create a specific logger object for this file
logger = logging.getLogger(__name__)

app = FastAPI(title="Dispatcher")

# Defining metrics for prometheus
REQUEST_COUNT  = Counter("dispatcher_requests_total", "Total requests received")
DROPPED_COUNT  = Counter("dispatcher_requests_dropped_total", "Requests dropped")
LATENCY_HIST   = Histogram("dispatcher_latency_seconds", "End-to-end latency",
                            buckets=[0.05,0.1,0.2,0.3,0.5,0.75,1.0,2.0,5.0])
QUEUE_LENGTH   = Gauge("dispatcher_queue_length", "Current queue length")
WORKER_COUNT   = Gauge("dispatcher_worker_count", "Current number of workers")

# Configuring variables for inference server and queue
INFERENCE_URL   = os.getenv("INFERENCE_URL", "http://localhost:8080")
MAX_QUEUE_SIZE  = int(os.getenv("MAX_QUEUE", "500"))
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "10.0"))
NUM_WORKERS     = int(os.getenv("NUM_WORKERS", "1"))

# Initialise the queue and number of workers
queue: asyncio.Queue = None
current_workers: int = 0


# Dynamically adjust the number of available worker pods after scale-up or scale-down
async def scale_workers(n: int):
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

# It handles the request being sent to inference pod such that one request is sent to inference pod and shuts down the inference pod if request is None
async def queue_worker(worker_id: int):
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


# Initialise shared state and launch workers at start
@app.on_event("startup")
async def startup():
    global queue
    queue = asyncio.Queue(maxsize=MAX_QUEUE_SIZE)
    await scale_workers(NUM_WORKERS)
    logger.info(f"Dispatcher ready — inference at {INFERENCE_URL}")


# Main dispatcher pod endpoint
@app.post("/predict")
async def dispatch(file: UploadFile = File(...)):
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

# Matches the current worker count to the autoscaler
@app.post("/scale")
async def scale(replicas: int = Query(..., gt=0, le=20)):
    logger.info(f"Scale request received: {replicas} replicas")
    await scale_workers(replicas)
    return {"workers": current_workers}

# Endpoint for Prometheus to scrape
@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

# Endpoint for Liveness probe
@app.get("/health")
def health():
    return {
        "status": "ok",
        "queue_size": queue.qsize() if queue else 0,
        "workers": current_workers
    }

# Endpoint that returns queue depth
@app.get("/queue_length")
def queue_length():
    return {"queue_length": queue.qsize() if queue else 0}
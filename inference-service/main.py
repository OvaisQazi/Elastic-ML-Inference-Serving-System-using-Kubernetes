import time
import torch
from torchvision.models import resnet18, ResNet18_Weights
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse
from prometheus_client import Histogram, Counter, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response
from PIL import Image
import io
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="ResNet18 Inference Service")

# Load model once at startup
weights = ResNet18_Weights.IMAGENET1K_V1
model = resnet18(weights=weights)
model.eval()
model = model.cpu()
preprocess = weights.transforms()

# Prometheus metrics
INFERENCE_LATENCY = Histogram(
    "inference_latency_seconds", "Inference latency",
    buckets=[0.05, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0]
)
INFERENCE_COUNT = Counter("inference_requests_total", "Total inference requests")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/predict")
async def predict(file: UploadFile = File(...)):
    INFERENCE_COUNT.inc()
    t_start = time.time()

    try:
        img_bytes = await file.read()
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid image: {e}")

    with torch.no_grad():
        inp = preprocess(img).unsqueeze(0)
        logits = model(inp)
        probs = torch.softmax(logits, dim=1)

    top5 = probs[0].topk(5)
    categories = weights.meta["categories"]
    results = [
        {"label": categories[i], "score": round(s.item(), 4)}
        for i, s in zip(top5.indices, top5.values)
    ]

    latency_ms = (time.time() - t_start) * 1000
    INFERENCE_LATENCY.observe(latency_ms / 1000)
    logger.info(f"Inference done in {latency_ms:.1f}ms")

    return JSONResponse({
        "predictions": results,
        "latency_ms": round(latency_ms, 2)
    })
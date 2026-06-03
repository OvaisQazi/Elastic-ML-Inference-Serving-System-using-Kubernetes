import time
import torch
import torchvision.transforms as T
from torchvision.models import resnet18, ResNet18_Weights
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse
from PIL import Image
import io
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="ResNet18 Inference Service")

# Load model ONCE at startup (not per request — critical for latency)
weights = ResNet18_Weights.IMAGENET1K_V1
model = resnet18(weights=weights)
model.eval()          # disable dropout/batchnorm training behavior
model = model.cpu()   # explicit CPU — never GPU

preprocess = weights.transforms()  # official preprocessing pipeline

@app.get("/health")
def health():
    """Kubernetes liveness/readiness probe."""
    return {"status": "ok"}

@app.post("/predict")
async def predict(file: UploadFile = File(...)):
    """
    Accept a JPEG/PNG image, run ResNet18, return top-5 labels.
    Design: one request at a time — no internal queue.
    The Dispatcher is responsible for all queuing.
    """
    t_start = time.time()
    try:
        img_bytes = await file.read()
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid image: {e}")

    # Preprocessing + inference (CPU)
    with torch.no_grad():
        inp = preprocess(img).unsqueeze(0)   # [1, 3, 224, 224]
        logits = model(inp)                   # [1, 1000]
        probs = torch.softmax(logits, dim=1)

    top5 = probs[0].topk(5)
    categories = weights.meta["categories"]
    results = [
        {"label": categories[i], "score": round(s.item(), 4)}
        for i, s in zip(top5.indices, top5.values)
    ]

    latency_ms = (time.time() - t_start) * 1000
    logger.info(f"Inference done in {latency_ms:.1f}ms")

    return JSONResponse({
        "predictions": results,
        "latency_ms": round(latency_ms, 2)
    })
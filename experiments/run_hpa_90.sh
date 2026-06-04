#!/bin/bash
# run_hpa_90.sh
# Experiment 2: HPA with CPU target 90%
# ─────────────────────────────────────

set -e

EXPERIMENT_NAME="hpa_90"
DISPATCHER_URL="http://localhost:9000"

echo "============================================"
echo " Experiment 2: HPA CPU=90%"
echo "============================================"

echo "[1/5] Removing custom autoscaler..."
kubectl delete deployment autoscaler-deployment --ignore-not-found
echo "      Done."

echo "[2/5] Resetting inference to 1 replica..."
kubectl scale deployment inference-deployment --replicas=1
kubectl rollout status deployment/inference-deployment
echo "      Done."

echo "[3/5] Applying HPA (CPU target=90%)..."
kubectl delete hpa inference-hpa-70 --ignore-not-found
kubectl apply -f hpa_90.yaml
echo "      Waiting 30s for HPA to initialise..."
sleep 30
kubectl get hpa inference-hpa-90
echo "      Done."

echo "[4/5] Starting load test — this will take ~10 minutes..."
cd ../load-tester
python run_experiment.py --name "$EXPERIMENT_NAME" --dispatcher "$DISPATCHER_URL"
cd ../experiments

echo "[5/5] Cleaning up HPA..."
kubectl delete hpa inference-hpa-90 --ignore-not-found
echo "      Done."

echo ""
echo "============================================"
echo " Experiment 2 complete."
echo " Results: load-tester/results/${EXPERIMENT_NAME}/"
echo "============================================"
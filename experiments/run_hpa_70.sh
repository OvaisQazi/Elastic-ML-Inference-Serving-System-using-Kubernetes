#!/bin/bash
# run_hpa_70.sh — Experiment 1: HPA CPU=70%

set -e

EXPERIMENT_NAME="hpa_70"
DISPATCHER_URL="http://localhost:9000"

echo "============================================"
echo " Experiment 1: HPA CPU=70%"
echo "============================================"

echo "[1/6] Removing custom autoscaler..."
kubectl delete deployment autoscaler-deployment --ignore-not-found
echo "      Done."

echo "[2/6] Resetting inference to 1 replica..."
kubectl scale deployment inference-deployment --replicas=1
kubectl rollout status deployment/inference-deployment
echo "      Done."

echo "[3/6] Applying HPA (CPU target=70%)..."
kubectl delete hpa --all --ignore-not-found
kubectl apply -f hpa_70.yaml
echo "      Waiting 30s for HPA to initialise..."
sleep 30
kubectl get hpa inference-hpa-70
echo "      Done."

echo "[4/6] Starting dispatcher sync sidecar..."
cd ../load-tester
python dispatcher_sync.py &
SYNC_PID=$!
echo "      Dispatcher sync PID=$SYNC_PID"
sleep 3
cd ../experiments

echo "[5/6] Starting load test (~10 minutes)..."
cd ../load-tester
python run_experiment.py --name "$EXPERIMENT_NAME" --dispatcher "$DISPATCHER_URL"
cd ../experiments

echo "[6/6] Cleaning up..."
kill $SYNC_PID 2>/dev/null || true
kubectl delete hpa inference-hpa-70 --ignore-not-found
echo "      Done."

echo ""
echo "============================================"
echo " Experiment 1 complete."
echo " Results: load-tester/results/${EXPERIMENT_NAME}/"
echo "============================================"
#!/bin/bash
# run_custom.sh — Experiment 3: Custom Autoscaler

set -e

EXPERIMENT_NAME="custom"
DISPATCHER_URL="http://localhost:9000"

echo "============================================"
echo " Experiment 3: Custom Autoscaler"
echo "============================================"

echo "[1/5] Removing any active HPA..."
kubectl delete hpa --all --ignore-not-found
echo "      Done."

echo "[2/5] Resetting inference to 1 replica..."
kubectl scale deployment inference-deployment --replicas=1
kubectl rollout status deployment/inference-deployment
echo "      Done."

echo "[3/5] Deploying custom autoscaler..."
kubectl apply -f ../autoscaler/k8s/autoscaler.yaml
echo "      Waiting 30s for autoscaler to initialise..."
sleep 30
kubectl get pods -l app=autoscaler
echo "      Done."

# No dispatcher_sync needed for custom experiment —
# the autoscaler already calls /scale itself after every scaling decision.

echo "[4/5] Starting load test (~10 minutes)..."
cd ../load-tester
python run_experiment.py --name "$EXPERIMENT_NAME" --dispatcher "$DISPATCHER_URL"
cd ../experiments

echo "[5/5] Done — leaving autoscaler running."

echo ""
echo "============================================"
echo " Experiment 3 complete."
echo " Results: load-tester/results/${EXPERIMENT_NAME}/"
echo "============================================"
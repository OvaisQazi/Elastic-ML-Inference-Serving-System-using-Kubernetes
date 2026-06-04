#!/bin/bash
# run_custom.sh
# Experiment 3: Custom autoscaler
# ─────────────────────────────────────

set -e

EXPERIMENT_NAME="custom"
DISPATCHER_URL="http://localhost:9000"

echo "============================================"
echo " Experiment 3: Custom Autoscaler"
echo "============================================"

echo "[1/5] Removing any active HPA..."
kubectl delete hpa inference-hpa-70 --ignore-not-found
kubectl delete hpa inference-hpa-90 --ignore-not-found
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

echo "[4/5] Starting load test — this will take ~10 minutes..."
cd ../load-tester
python run_experiment.py --name "$EXPERIMENT_NAME" --dispatcher "$DISPATCHER_URL"
cd ../experiments

echo "[5/5] Done — leaving autoscaler running."
echo "      To stop it: kubectl delete deployment autoscaler-deployment"

echo ""
echo "============================================"
echo " Experiment 3 complete."
echo " Results: load-tester/results/${EXPERIMENT_NAME}/"
echo "============================================"
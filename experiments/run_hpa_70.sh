#!/bin/bash
# run_hpa_70.sh
# Experiment 1: HPA with CPU target 70%
# ─────────────────────────────────────
# 1. Tears down custom autoscaler
# 2. Resets inference to 1 replica
# 3. Applies HPA at 70% CPU target
# 4. Runs the load tester
# 5. Cleans up HPA when done

set -e  # exit on any error

EXPERIMENT_NAME="hpa_70"
DISPATCHER_URL="http://localhost:9000"

echo "============================================"
echo " Experiment 1: HPA CPU=70%"
echo "============================================"

# ── Step 1: Tear down custom autoscaler ──────────────────────────────
echo "[1/5] Removing custom autoscaler..."
kubectl delete deployment autoscaler-deployment --ignore-not-found
echo "      Done."

# ── Step 2: Reset inference deployment to 1 replica ──────────────────
echo "[2/5] Resetting inference to 1 replica..."
kubectl scale deployment inference-deployment --replicas=1
kubectl rollout status deployment/inference-deployment
echo "      Done."

# ── Step 3: Apply HPA ─────────────────────────────────────────────────
echo "[3/5] Applying HPA (CPU target=70%)..."
kubectl delete hpa inference-hpa-90 --ignore-not-found   # remove other HPA if present
kubectl apply -f hpa_70.yaml
echo "      Waiting 30s for HPA to initialise..."
sleep 30
kubectl get hpa inference-hpa-70
echo "      Done."

# ── Step 4: Run load tester ───────────────────────────────────────────
echo "[4/5] Starting load test — this will take ~10 minutes..."
echo "      Results will be saved to load-tester/results/${EXPERIMENT_NAME}/"
cd ../load-tester
python run_experiment.py --name "$EXPERIMENT_NAME" --dispatcher "$DISPATCHER_URL"
cd ../experiments

# ── Step 5: Cleanup ───────────────────────────────────────────────────
echo "[5/5] Cleaning up HPA..."
kubectl delete hpa inference-hpa-70 --ignore-not-found
echo "      Done."

echo ""
echo "============================================"
echo " Experiment 1 complete."
echo " Results: load-tester/results/${EXPERIMENT_NAME}/"
echo "============================================"
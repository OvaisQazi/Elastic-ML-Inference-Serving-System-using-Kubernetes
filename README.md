## Steps:

- Start Docker

- Start Minikube

- enable minikube metrics server
    minikube addons enable metrics-server

- switch to minikube docker env
    eval $(minikube docker-env)

- Build the 3 docker images
    docker build --no-cache -t inference-service:latest inference-service/ 
    docker build --no-cache -t dispatcher:latest dispatcher/ 
    docker build --no-cache -t autoscaler:latest autoscaler/

- Deploy the pods
    kubectl apply -f inference-service/k8s/ 
    kubectl apply -f dispatcher/k8s/ 
    kubectl apply -f monitoring/prometheus-config-yaml 
    kubectl apply -f monitoring/prometheus.yaml 
    kubectl apply -f autoscaler/k8s/autoscaler.yaml

- Make the shell scripts executable
    chmod +x experiments/run_hpa_70.sh 
    chmod +x experiments/run_hpa_90.sh 
    chmod +x experiments/run_custom.sh

- port forward the 3 services
    kubectl port-forward svc/inference-service 8080:8080 
    kubectl port-forward svc/dispatcher-service 9000:9000 
    kubectl port-forward svc/prometheus-service 9090:9090 

- If running hpa 70 or hpa 90 first run the dispatcher sync py file in load-tester directory
    python3 dispatcher_sync.py (not needed for custom autoscaler)

- Run the script which you want to test (one at a time inside the experiments directory)
    ./run_custom.sh
    ./run_hpa_70.sh
    ./run_hpa_90.sh

- To check the replicas being made and use
    kubectl get deployment inference-deployment -w (for custom autoscaler)
    kubectl get hpa inference-hpa-70 -w (for hpa 70)
    kubectl get hpa inference-hpa-90 -w (for hpa 90)

(You need to add sample images to the sample imaged directory inside load-tester directory)
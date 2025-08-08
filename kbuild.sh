./build-optimized.sh
kubectl delete -f k8s/deployment.yaml
kubectl apply -f k8s/deployment.yaml

kubectl run locust-bench \
  -it \
  --rm \
  --restart=Never \
  --image=kasbench/globeco-benchmark-coordinator \
  --command -- \
  uv run locust -f ./scripts/calibration.py \
    --host=http://globeco-portfolio-management-portal:3000 \
    --headless \
    -t 5m \
    -u 1 \
    --spawn-rate 1 \
    --tags globeco-portfolio-service \
    CalibrationUser

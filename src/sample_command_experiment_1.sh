./experiments/runner.py \
--bucket-name-prefix experiment-1-20251224 \
--trial-lengths-minutes 5 \
--users 80 \
--trial-numbers -60 \
--host http://globeco.local:32080 \
--resource-profile default \
--collect-thermal-metrics

python ./experiments/run_baseline_idle_thermal_metrics.py
./experiments/runner.py \
--bucket-name-prefix experiment-3-20260123 \
--trial-lengths-minutes 5 \
--users 40 \
--trial-numbers -60 \
--host http://globeco.local:32080 \
--resource-profiles configuration-10-40-False configuration-10-100-False \
--replicas 1 2 3 4 5
--wait-for-cooling


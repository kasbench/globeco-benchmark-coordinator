./experiments/runner.py \
--bucket-name-prefix experiment-5-20260129 \
--trial-lengths-minutes 5 \
--users 40 80 \
--trial-numbers -60 \
--host http://globeco.local:32080 \
--resource-profiles configuration-10-100-False configuration-10-150-False configuration-10-200-False \
configuration-10-250-False configuration-10-300-False \
--replicas 1  \
--no-validate \
--wait-for-cooling


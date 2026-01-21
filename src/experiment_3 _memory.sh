./experiments/runner.py \
--bucket-name-prefix experiment-3-20260117 \
--trial-lengths-minutes 5 \
--users 40 \
--trial-numbers -60 \
--host http://globeco.local:32080 \
--resource-profiles configuration-20-70-False \
configuration-30-70-False configuration-40-70-False configuration-50-70-False \
--wait-for-cooling


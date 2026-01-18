./experiments/runner.py \
--bucket-name-prefix experiment-3-20260117 \
--trial-lengths-minutes 5 \
--users 40 \
--trial-numbers -60 \
--host http://globeco.local:32080 \
--resource-profiles configuration-10-00-True configuration-10-10-True configuration-10-20-True configuration-10-30-True \
configuration-10-40-True configuration-10-50-True configuration-10-60-True  \
configuration-10-40-False configuration-10-50-False configuration-10-60-False configuration-10-70-False \
configuration-10-80-False \
--wait-for-cooling


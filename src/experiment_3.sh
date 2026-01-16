./experiments/runner.py \
--bucket-name-prefix experiment-3-20260113 \
--trial-lengths-minutes 5 \
--users 40 \
--trial-numbers -60 \
--host http://globeco.local:32080 \
--resource-profiles configuration-000 configuration-001 configuration-01 configuration-02 configuration-03   \
--wait-for-cooling


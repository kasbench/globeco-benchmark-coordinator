./experiments/runner.py \
--bucket-name-prefix experiment-3-20260113 \
--trial-lengths-minutes 5 \
--users 40 \
--trial-numbers -30 \
--host http://globeco.local:32080 \
--resource-profiles configuration-01 configuration-02 configuration-03 configuration-04 configuration-05  \
--wait-for-cooling


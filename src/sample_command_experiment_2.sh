./experiments/runner.py \
--bucket-name-prefix experiment-2-20251225 \
--trial-lengths-minutes 1\
--users 10 15 20 25 30 35 40 45 50 55 60 65 70 75 80 \
--trial-numbers -60 \
--host http://globeco.local:32080 \
--resource-profile default-2 \
--wait-for-cooling


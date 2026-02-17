./experiments/runner.py \
--bucket-name-prefix experiment-5-20260129 \
--trial-lengths-minutes 5 \
--users 40 80 \
--trial-numbers -60 \
--host http://globeco.local:32080 \
--resource-profiles configuration-10-100-False configuration_nl-20-000-True configuration_nl-20-025-True \
 configuration_nl-20-050-True configuration_nl-20-075-True configuration_nl-20-100-True  \
 configuration_nl-20-125-True configuration_nl-20-150-True configuration_nl-20-175-True \
 configuration_nl-20-200-True \
--replicas 1  \
--wait-for-cooling


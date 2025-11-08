import os
import traceback
from datetime import datetime, timedelta
import random
import time
from typing import Any

import common
import ssh
import prometheus
from common import get_threshold_lookup, ensure_bucket_exists, file_count, file_exists, \
    scale_microservice_deployments, initialize_databases, initialize_environments_for_resource_trial, \
    validate_environments, wait_for_all_rollouts, wait_for_cooling, save_to_minio, run_test_in_kubernetes
from constants import NODE_METRICS, microservices
from common import minio_client


def get_kubernetes_resources(version_name: str) -> list[dict[str, dict[str, str]] | Any] | None:
    if version_name == "baseline":
        return [
            {'globeco-allocation-service': {'cpu_request': '200m', 'cpu_limit': '200m',
                                            'memory_request': '100Mi', 'memory_limit': '100Mi'}},
            {'globeco-confirmation-service': {'cpu_request': '200m', 'cpu_limit': '200m',
                                              'memory_request': '100Mi', 'memory_limit': '100Mi'}},
            {'globeco-execution-service': {'cpu_request': '600m', 'cpu_limit': '600m',
                                           'memory_request': '900Mi', 'memory_limit': '900Mi'}},
            {'globeco-fix-engine': {'cpu_request': '200m', 'cpu_limit': '200m',
                                    'memory_request': '100Mi', 'memory_limit': '100Mi'}},
            {'globeco-order-generation-service': {'cpu_request': '1', 'cpu_limit': '1',
                                       'memory_request': '700Mi', 'memory_limit': '700Mi'}},
            {'globeco-order-service': {'cpu_request': '1', 'cpu_limit': '1',
                                       'memory_request': '1100Mi', 'memory_limit': '1100Mi'}},
            {'globeco-portfolio-accounting-service': {'cpu_request': '200m', 'cpu_limit': '200m',
                                                      'memory_request': '100Mi', 'memory_limit': '100Mi'}},
            {'globeco-portfolio-management-portal': {'cpu_request': '600m', 'cpu_limit': '600m',
                                                      'memory_request': '200Mi', 'memory_limit': '200Mi'}},
            {'globeco-portfolio-service': {'cpu_request': '300m', 'cpu_limit': '300m',
                                           'memory_request': '200Mi', 'memory_limit': '200Mi'}},
            {'globeco-pricing-service': {'cpu_request': '1', 'cpu_limit': '1',
                                         'memory_request': '1000Mi', 'memory_limit': '1000Mi'}},
            {'globeco-security-service': {'cpu_request': '300m', 'cpu_limit': '300m',
                                           'memory_request': '200Mi', 'memory_limit': '200Mi'}},
            {'globeco-trade-service': {'cpu_request': '1', 'cpu_limit': '1',
                                       'memory_request': '1000Mi', 'memory_limit': '1000Mi'}}
        ]

    raise ValueError(f"Unknown version: {version_name}")



def get_trials(replicas:list[int], times:list[str], users:list[int], iterations:int):
    trials = []
    for replica in replicas:
        for time in times:
            for user in users:
                for iteration in range(iterations):
                    trials.append({'replica': replica, 'time': time, 'user': user, 'iteration': iteration})

    return trials


def make_trial_file_name(trial:dict, extension:str) -> str:
    filename = f"trial_{trial["user"]}_{trial['replica']}_{trial['time']}{extension}"
    return filename


def get_next_trial(minio_client,
            trials,
            log_bucket_name,
            log_extension,
            metric_bucket_names,
            metric_extensions):
    number_of_trials = len(trials)
    all_buckets = [log_bucket_name] + metric_bucket_names
    all_extensions = [log_extension] + metric_extensions

    # Check to see if we have already completed all trials
    counter = 0
    for bucket_name in all_buckets:
        if file_count(minio_client, bucket_name) >= number_of_trials:
            counter += 1
    if counter == len(all_buckets):
        print(f"All {number_of_trials} trials completed")
        return None

    # If not, pick one that has not been completed
    while True:
        trial = random.choice(trials)
        for bucket_name, extension in zip(all_buckets, all_extensions):
            filename = make_trial_file_name(trial, extension)
            # If any file in the trial doesn't exist, we will rerun
            if not file_exists(minio_client, bucket_name, filename):
                return trial




def run_resource_trial(trial, verbose=False):

    print(f"Running trial number {trial["iteration"]} for {trial["time"]} with {trial["replica"]} replicas and {trial["user"]} users.")
    raw_output = run_test_in_kubernetes(time_expression=trial["time"], user_count=trial["user"], spawn_rate=trial["user"],
                                        verbose=verbose)
    return raw_output


def initialize_only(kubernetes_resource_profile:str= "baseline", replicas=1, validate=True):
    kubernetes_resources = get_kubernetes_resources(kubernetes_resource_profile)
    initialize(kubernetes_resources, replicas, validate=validate)

# Add method to execute the following kubectl command and save the results:
# kubectl exec -it svc/globeco-debug-tools -- psql -h globeco-trade-service-postgresql -U postgres -c "select sum(quantity_ordered) "quantity_ordered", sum(quantity_placed) "quantity_placed", sum(quantity_filled) "quantity_filled" from execution;"

def get_roundtrip_trade_results(bucket_name, trial):
    filename = make_trial_file_name(trial, "-roundrip.json")
    command = 'kubectl exec -it svc/globeco-debug-tools -- psql -h globeco-trade-service-postgresql -U postgres -tAc "select json_agg(t) from (select sum(quantity_ordered) quantity_ordered, sum(quantity_placed) quantity_placed, sum(quantity_filled) quantity_filled from execution) t;"'
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    # sample output: [{"quantity_ordered":30210.00000000,"quantity_placed":30210.00000000,"quantity_filled":30165.00000000}]
    print(f"Saving {bucket_name}/{filename}")
    with tempfile.NamedTemporaryFile(mode='w+', delete=True) as tmp:
        tmp.write(result.stdout)
        minio_client.fput_object(bucket_name, filename, tmp.name)




def run(replicas:list[int]=None, kubernetes_resource_profile:str= "baseline", times:list[str]=None, users:list[int]=None,
        iterations:int=30, bucket_name_prefix=None, validate=True, wait_for_cooling_before_run=True) -> int:

    # Process arguments
    if replicas is None:
        replicas = [1, 2, 4, 6]
    if users is None:
        users = [75]
    if times is None:
        times = ["10m"]
    if bucket_name_prefix is None:
        raise ValueError("bucket_name_prefix cannot be None")

    kubernetes_resources = get_kubernetes_resources(kubernetes_resource_profile)

    thermal_threshold_lookup = get_threshold_lookup()

    metrics = ["container_cpu_usage_seconds_total", "container_cpu_cfs_throttled_seconds_total",
                "container_memory_working_set_bytes"]
    calculate_rates = [True,  True, False]
    extensions = ["-logs.txt", "-cpu-usage.parquet",  "-cpu-throttled.parquet", "-memory-wsb.parquet"]
    log_extension = extensions[0]
    metric_extensions = extensions[1:]
    bucket_extensions = ["-logs-raw", "-roundtrip", "-cpu-usage",  "-cpu-throttled", "-memory-wsb"]
    bucket_names = [f"{bucket_name_prefix}{bucket_extension}" for bucket_extension in bucket_extensions]
    node_bucket_name = f"{bucket_name_prefix}-node"
    log_bucket_name = bucket_names[0]
    roundtrip_bucket_name = bucket_names[1]
    metric_bucket_names = bucket_names[2:]
    

    for bucket_name in bucket_names:
        ensure_bucket_exists(minio_client, bucket_name)
    ensure_bucket_exists(minio_client, node_bucket_name)

    trials = get_trials(replicas, times, users, iterations)

    while trial := get_next_trial(minio_client, trials, log_bucket_name, log_extension, metric_bucket_names, metric_extensions):

        try:
            print(f"Starting trial: {trial}")
            
            print("Wait up to 15 minutes for cooling")
            if wait_for_cooling_before_run:
                wait_for_cooling(thermal_threshold_lookup, max_wait_seconds=900)

            print("Setting CPU governor to performance mode")
            ssh.set_cpu_governor_to_performance(revert=True)

            initialize(kubernetes_resources, trial["replica"], validate)
            time.sleep(10)  # Stabilization
            
            
            
            ssh.set_cpu_governor_to_performance()
            
            start_time = datetime.now()
            print(f"Start time: {start_time.strftime("%Y-%m-%d %H:%M:%S")}")
            
            raw_output = run_resource_trial(trial)
            
            end_time = datetime.now()
            print(f"End time: {end_time.strftime("%Y-%m-%d %H:%M:%S")}")
            
            ssh.set_cpu_governor_to_performance(revert=True)
            
            filename = make_trial_file_name(trial, log_extension)
            save_to_minio(minio_client, raw_output, log_bucket_name, filename)
            get_roundtrip_trade_results(roundtrip_bucket_name, trial)
            for metric, metric_bucket_name, metric_extension, calculate_rate in zip(metrics, metric_bucket_names,
                                                                                    metric_extensions,
                                                                                    calculate_rates):
                prom = prometheus.get_prometheus_connection()
                prometheus_data = prometheus.get_prometheus_data(prom, microservices, metric, start_time, end_time,
                                                                 calculate_rate=calculate_rate)
                filename = make_trial_file_name(trial, metric_extension)
                prometheus_data.to_parquet(filename)
                minio_client.fput_object(metric_bucket_name, filename, filename)
                os.remove(filename)
            for node, node_metrics in NODE_METRICS.items():
                for metric in node_metrics:
                    prom = prometheus.get_prometheus_connection()
                    prometheus_data = prometheus.get_prometheus_node_data(prom, node, metric, start_time, end_time,
                                                                          verbose=False)
                    filename = make_trial_file_name(trial, f"-{node}-{metric}.parquet")
                    prometheus_data.to_parquet(filename)
                    minio_client.fput_object(node_bucket_name, filename, filename)
                    os.remove(filename)


        except Exception as e:
            print(f"Error in trial {trial}: {e}.\n{traceback.format_exc()}")
            continue

    ssh.set_cpu_governor_to_performance(revert=True)
    print("Scaling down microservices")
    scale_microservice_deployments(1)

    return 0


def initialize(kubernetes_resources: list[dict[str, dict[str, str]] | Any] | None, replicas: int, validate: bool):
    print("Scaling down microservices")
    scale_microservice_deployments(0)
    print("Initializing databases")
    initialize_databases()
    print("Initializing environments for resource trial")
    initialize_environments_for_resource_trial(replicas=replicas, overrides=kubernetes_resources)
    print("Environment Initialized.")
    if validate:
        print("Waiting for 15 seconds before validation...")
        time.sleep(15)  # Short wait before validation
        validate_environments(overrides=kubernetes_resources)
        print("Environment validation complete.  Starting 45 second wait.")
        time.sleep(45)  # It will take at least this long.  Waiting leaves time for stabilization.
    else:
        print("Starting 60 second wait.")
        time.sleep(60)  # It will take at least this long.  Waiting leaves time for stabilization.

    wait_for_all_rollouts()




if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Run horizontal scaling experiment')
    parser.add_argument('bucket_name_prefix', type=str, help='Prefix for bucket names (required)')
    parser.add_argument('--replicas', type=int, nargs='+', default=[1, 2, 4, 6], 
                        help='List of replica counts to test (default: 1 2 4 6)')
    parser.add_argument('--kubernetes-resource-profile', type=str, default='baseline',
                        help='Kubernetes resource profile to use (default: baseline)')
    parser.add_argument('--times', type=str, nargs='+', default=['10m'],
                        help='List of time expressions for tests (default: 10m)')
    parser.add_argument('--users', type=int, nargs='+', default=[75],
                        help='List of user counts to test (default: 75)')
    parser.add_argument('--iterations', type=int, default=30,
                        help='Number of iterations per configuration (default: 30)')
    parser.add_argument('--no-validate', action='store_false', dest='validate',
                        help='Skip environment validation')
    parser.add_argument('--no-wait-for-cooling', action='store_false', dest='wait_for_cooling_before_run',
                        help='Skip waiting for cooling before run')
    
    args = parser.parse_args()
    
    run(
        replicas=args.replicas,
        kubernetes_resource_profile=args.kubernetes_resource_profile,
        times=args.times,
        users=args.users,
        iterations=args.iterations,
        bucket_name_prefix=args.bucket_name_prefix,
        validate=args.validate,
        wait_for_cooling_before_run=args.wait_for_cooling_before_run
    )
import os
import traceback
from datetime import datetime, timedelta
import random
import time
from typing import Any

from experiments.calibration import common, ssh, prometheus
from experiments.calibration.common import get_threshold_lookup, ensure_bucket_exists, file_count, file_exists, \
    scale_microservice_deployments, initialize_databases, initialize_environments_for_resource_trial, \
    validate_environments, wait_for_all_rollouts, wait_for_cooling, save_to_minio
from experiments.calibration.constants import NODE_METRICS, microservices


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


def run_test_in_kubernetes(time_expression="5m", user_count="1", spawn_rate="1", replicas=1, verbose=False):
    pod_name = f"locust-bench-{int(time.time())}"

    command_line = [
        "uv", "run", "locust", "-f", "./scripts/end_to_end_sequential.py",
        "--host=http://globeco-portfolio-management-portal:3000",
        "--headless", "-t", time_expression, "-u", user_count,
        "--spawn-rate", spawn_rate, "--json", "--skip-log", "--only-summary", "--reset-stats",
        "--loglevel", "ERROR", "EndToEndUser"
    ]

    try:
        # Create pod
        subprocess.run([
                           "kubectl", "run", pod_name, "--restart=Never",
                           "-n", namespace,
                           "--image=kasbench/globeco-benchmark-coordinator",
                           "--command", "--"
                       ] + command_line, check=True)

        # Wait for completion and get logs
        if verbose:
            print("Waiting for pod to complete...")
        time.sleep(55)  # Give pod plenty of time to start.  It's ok that this is unnecessarily long, since
        # we will be waiting for the pod to finish in the next step, and all runs are at
        # least 1 minute.

        # Follow logs until pod completes
        logs_result = subprocess.run([
            "kubectl", "logs", "-f", pod_name, "-n", namespace,
        ], capture_output=True, text=True, timeout=600)

        # Clean up
        subprocess.run(["kubectl", "delete", "pod", pod_name, "-n", namespace])

        # Return results

        return logs_result.stdout

    except Exception as e:
        subprocess.run(["kubectl", "delete", "pod", pod_name])
        raise e


def run_resource_trial(trial, verbose=False):

    print(f"Running trial number {trial["iteration"]} for {trial["time"]} with {trial["replica"]} replicas and {trial["user"]} users.")
    raw_output = run_test_in_kubernetes(time_expression=trial_length, user_count=trial_users, spawn_rate=trial_users,
                                        verbose=verbose)
    return raw_output
    pass


def run(replicas:list[int]=None, kubernetes_resources:str= "baseline", times:list[str]=None, users:list[int]=None,
        iterations:int=30, bucket_name_prefix=None, validate=True, wait_for_cooling_before_run=True) -> int:

    # Process arguments
    if replicas is None:
        replicas = [1, 2, 4, 8, 16]
    if users is None:
        users = [75]
    if times is None:
        times = ["10m"]
    if bucket_name_prefix is None:
        raise ValueError("minio_prefix cannot be None")

    minio_client = common.minio_client()
    kubernetes_resources = get_kubernetes_resources(kubernetes_resources)

    thermal_threshold_lookup = get_threshold_lookup()

    metrics = ["container_cpu_usage_seconds_total", "container_cpu_cfs_throttled_seconds_total",
                "container_memory_working_set_bytes"]
    calculate_rates = [True,  True, False]
    extensions = ["-logs.txt", "-cpu-usage.parquet",  "-cpu-throttled.parquet", "-memory-wsb.parquet"]
    log_extension = extensions[0]
    metric_extensions = extensions[1:]
    bucket_extensions = ["-logs-raw", "-cpu-usage",  "-cpu-throttled", "-memory-wsb"]
    bucket_names = [f"{bucket_name_prefix}{bucket_extension}" for bucket_extension in bucket_extensions]
    node_bucket_name = f"{bucket_name_prefix}-node"
    log_bucket_name = bucket_names[0]
    metric_bucket_names = bucket_names[1:]

    for bucket_name in bucket_names:
        ensure_bucket_exists(minio_client, bucket_name)
    ensure_bucket_exists(minio_client, node_bucket_name)

    trials = get_trials(replicas, times, users, iterations)

    while trial := get_next_trial(minio_client, trials, log_bucket_name, log_extension, metric_bucket_names, metric_extensions):

        try:
            print(f"Starting trial: {trial}")
            print("Setting CPU governor to performance mode")
            ssh.set_cpu_governor_to_performance(revert=True)
            print("Scaling down microservices")
            scale_microservice_deployments(0)
            print("Initializing databases")
            initialize_databases()
            print("Initializing environments for resource trial")
            initialize_environments_for_resource_trial(trial, replicas=trial["replicas"], overrides=kubernetes_resources)
            print("Environment Initialized.")
            if validate:
                print("Waiting for 15 seconds before validation...")
                time.sleep(15)  # Short wait before validation
                validate_environments(trial, overrides=kubernetes_resources)
                print("Environment validation complete.  Starting 45 second wait.")
                time.sleep(45)  # It will take at least this long.  Waiting leaves time for stabilization.
            else:
                print("Starting 60 second wait.")
                time.sleep(60)  # It will take at least this long.  Waiting leaves time for stabilization.

            wait_for_all_rollouts()
            time.sleep(10)  # Stabilization
            print("Wait up to 5 minutes for cooling")
            if wait_for_cooling_before_run:
                wait_for_cooling(thermal_threshold_lookup)
            ssh.set_cpu_governor_to_performance()
            start_time = datetime.now()
            print(f"Start time: {start_time.strftime("%Y-%m-%d %H:%M:%S")}")
            raw_output = run_resource_trial(trial)
            end_time = datetime.now()
            ssh.set_cpu_governor_to_performance(revert=True)
            print(f"End time: {end_time.strftime("%Y-%m-%d %H:%M:%S")}")
            filename = make_trial_file_name(trial, log_extension)
            save_to_minio(minio_client, raw_output, log_bucket_name, filename)
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








    return 0




if __name__ == "__main__":
    run()
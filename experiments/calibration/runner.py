import os
import subprocess
import time
import traceback
from datetime import datetime, timedelta


from minio import Minio

from experiments.calibration import ssh, prometheus
from experiments.calibration.calibration_experiment import get_resource_trials, get_next_resource_trial, \
    make_resource_trial_file_name
from experiments.calibration.common import get_threshold_lookup, ensure_bucket_exists, scale_microservice_deployments, \
    initialize_databases, initialize_environments_for_resource_trial, validate_environments, wait_for_all_rollouts, \
    wait_for_cooling
from experiments.calibration.constants import NODE_METRICS


def run(
        bucket_name_prefix,
        trial_numbers = None,
        users = None,
        resource_profile = "default",
        trial_lengths_minutes = None,
        microservices = None,
        replicas = 1,
        validate = True,
        verbose = False,
        overrides = None,
        wait_for_cooling_before_run = False,
    ):
        
    minio_client = Minio(
        "minio:9000",  
        access_key= os.environ['MINIO_ACCESS_KEY'],
        secret_key= os.environ['MINIO_SECRET_KEY'],
        secure=False  # Set to True for production with TLS
    )

    threshold_lookup = get_threshold_lookup()

    metrics = ["container_cpu_usage_seconds_total", "container_cpu_usage_seconds_total", "container_cpu_cfs_throttled_seconds_total", 
                "container_memory_working_set_bytes"]
    calculate_rates = [True, False, True, False]
    extensions = ["-logs.json", "-cpu-usage.parquet", "-cpu-usage-raw.parquet", "-cpu-throttled.parquet", "-memory-wsb.parquet"]
    log_extension = extensions[0]
    metric_extensions = extensions[1:]
    bucket_extensions = ["-logs-raw", "-cpu-usage", "-cpu-usage-raw", "-cpu-throttled", "-memory-wsb"]
    bucket_names = [f"{bucket_name_prefix}{bucket_extension}" for bucket_extension in bucket_extensions]
    node_bucket_name = f"{bucket_name_prefix}-node"
    log_bucket_name = bucket_names[0]
    metric_bucket_names = bucket_names[1:]

    for bucket_name in bucket_names:
        ensure_bucket_exists(minio_client, bucket_name)
    ensure_bucket_exists(minio_client, node_bucket_name)

    trials = get_resource_trials(
            trial_numbers=trial_numbers,
            trial_lengths=[f"{length}m" for length in trial_lengths_minutes],
            trial_users=[str(tu) for tu in users])

    ssh.set_cpu_governor_to_performance(revert=True) ## Ensure we start in default state
    
    while trial := get_next_resource_trial(
            minio_client, 
            trials, 
            log_bucket_name,
            log_extension,
            metric_bucket_names,
            metric_extensions):
        try:
            print(f"Starting trial: {trial}")
            print("Setting CPU governor to performance mode")
            ssh.set_cpu_governor_to_performance(revert=True)
            print("Scaling down microservices")
            scale_microservice_deployments(0)
            print("Initializing databases")
            initialize_databases()
            print("Initializing environments for resource trial")
            initialize_environments_for_resource_trial(replicas=replicas, overrides=overrides)
            print("Environment Initialized.")
            if validate:
                print("Waiting for 15 seconds before validation...")
                time.sleep(15) # Short wait before validation
                validate_environments(overrides=overrides)
                print("Environment validation complete.  Starting 45 second wait.")
                time.sleep(45) # It will take at least this long.  Waiting leaves time for stabilization.
            else:
                print("Starting 60 second wait.")
                time.sleep(60) # It will take at least this long.  Waiting leaves time for stabilization.
            
            wait_for_all_rollouts()
            time.sleep(10) # Stabilization
            print("Wait up to 5 minutes for cooling")
            if wait_for_cooling_before_run: 
                wait_for_cooling(threshold_lookup)
            ssh.set_cpu_governor_to_performance()
            start_time = datetime.now()
            print(f"Start time: {start_time.strftime("%Y-%m-%d %H:%M:%S")}")

            trial_num, trial_length, trial_users = trial

            log_db_filename = f"trial_{trial_num}_{trial_length}_{trial_users}_{datetime.now().strftime('%Y%m%d%H%M%S')}.db"

            command_line = [
                "uv", "run", "locust", "-f", "./scripts/end_to_end_sequential.py",
                "--host=http://globeco-portfolio-management-portal:3000",
                "--headless", "-t", trial_length, "-u", trial_users,
                "--spawn-rate", trial_users, "--json", "--skip-log", "--only-summary", "--reset-stats",
                "--sqlite_db", log_db_filename, 
                "--loglevel", "ERROR", "BenchmarkUser"
            ]

            try:
                subprocess.run(command_line, check=True)

            except Exception as e:
                print(f"Error: {e}")

            end_time = datetime.now()

            ssh.set_cpu_governor_to_performance(revert=True)    
            print(f"End time: {end_time.strftime("%Y-%m-%d %H:%M:%S")}")
            # filename = make_resource_trial_file_name(trial, "")
            save_to_minio(minio_client, log_db_filename, log_bucket_name, log_db_filename)


            for metric, metric_bucket_name, metric_extension, calculate_rate in zip(metrics, metric_bucket_names, metric_extensions, calculate_rates):
                prom = prometheus.get_prometheus_connection()
                prometheus_data = prometheus.get_prometheus_data(prom, microservices, metric, start_time, end_time, calculate_rate=calculate_rate)
                filename = make_resource_trial_file_name(trial, metric_extension)
                prometheus_data.to_parquet(filename)
                minio_client.fput_object(metric_bucket_name, filename, filename)
                os.remove(filename)
            for node, node_metrics in NODE_METRICS.items():
                for metric in node_metrics:
                    prom = prometheus.get_prometheus_connection()
                    prometheus_data = prometheus.get_prometheus_node_data(prom, node, metric, start_time, end_time, verbose=False)
                    filename = make_resource_trial_file_name(trial, f"-{node}-{metric}.parquet")
                    prometheus_data.to_parquet(filename)
                    minio_client.fput_object(node_bucket_name, filename, filename)
                    os.remove(filename)
                

        except Exception as e:
            print(f"Error in trial {trial}: {e}.\n{traceback.format_exc()}")
            continue
            
    ssh.set_cpu_governor_to_performance(revert=True)    
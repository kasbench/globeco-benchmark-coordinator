#!/usr/bin/env python3
    
import os
import subprocess
import time
import traceback
from datetime import datetime, timedelta
import random
import argparse
import pytz
    

from minio import Minio

import ssh, prometheus
from common import get_threshold_lookup, ensure_bucket_exists, scale_microservice_deployments, \
    initialize_databases, initialize_environments_for_resource_trial, validate_environments, wait_for_all_rollouts, \
    wait_for_cooling, save_to_minio, file_exists, get_pod_conditions
from constants import NODE_METRICS
from environment_check import validate_environment_health_during_trial, get_pod_restarts_for_namespace


def get_resource_trials(trial_numbers=list(range(30)), 
        trial_lengths=["10m"], trial_users=["50"]):
        return [(trial_num, trial_length, trial_user) 
            for trial_num in trial_numbers
            for trial_length in trial_lengths
            for trial_user in trial_users]


def make_resource_trial_file_name(trial, extension):
    trial_num, trial_length, trial_workers = trial
    return f"trial-{trial_workers}-{trial_length}-{trial_num}{extension}"


def get_next_resource_trial(
            minio_client, 
            trials, 
            log_bucket_name,
            log_extension,
            metric_bucket_names,
            metric_extensions):

    number_of_trials = len(trials)        
    all_buckets = [log_bucket_name] + metric_bucket_names
    all_extensions = [log_extension] + metric_extensions

    trial_set = set(trials)
    
    while True:
        if len(trial_set) == 0:
            print("All trials complete")
            return None 
        trial = random.choice(list(trial_set))
        for bucket_name, extension in zip(all_buckets, all_extensions):
            filename = make_resource_trial_file_name(trial, extension)
            # If any file in the trial doesn't exist, we will rerun
            if not file_exists(minio_client, bucket_name, filename):
                print(f"File {bucket_name}/{filename} does not exist for {trial}")
                return trial
        trial_set.remove(trial)


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
        skip_initialization = True, 
        host = "http://globeco-portfolio-management-portal:3000",
        collect_thermal_metrics = False,
        tz="America/New_York"
    ):

    if trial_numbers and len(trial_numbers) == 1 and trial_numbers[0] < 0:
        trial_numbers = range(-trial_numbers[0])
    if trial_numbers is None:
        trial_numbers = [1, 2, 3]
    if users is None:
        users = [1]
    if trial_lengths_minutes is None:
        trial_lengths_minutes = [30]
    if microservices is None:
        microservices = ["all"]
    if overrides is None:
        overrides = []

    if overrides and resource_profile != "default":
        raise RuntimeError("Cannot specify overrides and resource_profile at the same time")
        
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
    extensions = [".db", "-cpu-usage.parquet", "-cpu-usage-raw.parquet", "-cpu-throttled.parquet", "-memory-wsb.parquet"]
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
    error_log_name = f"error_log_{datetime.now().strftime('%Y%m%d%H%M%S')}.txt"
    print(f"Error log: {error_log_name}")   
    number_of_errors = 0 
    
    while trial := get_next_resource_trial(
            minio_client, 
            trials, 
            log_bucket_name,
            log_extension,
            metric_bucket_names,
            metric_extensions):
        try:
            print(f"Starting trial: {trial}")
            print("Setting CPU governor to default mode")
            ssh.set_cpu_governor_to_performance(revert=True)
            if not skip_initialization:
                print("Scaling down microservices")
                scale_microservice_deployments(0)
                print("Initializing databases")
                initialize_databases()
                print("Initializing environments for resource trial")
                overrides = initialize_environments_for_resource_trial(replicas=replicas, overrides=overrides, resource_profile=resource_profile)
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
            if wait_for_cooling_before_run: 
                print("Wait up to 5 minutes for cooling")
                wait_for_cooling(threshold_lookup)
            
            print("Setting CPU governor to performance mode")
            ssh.set_cpu_governor_to_performance()
            stability_start_time = datetime.now()

            print("Checking pod conditions before trial")
            prior_pod_restarts = get_pod_restarts_for_namespace()
            prior_pod_conditions = get_pod_conditions(namespace="globeco", raise_exception_on_not_ready=True)
            start_time = datetime.now()
            tz_object = pytz.timezone(tz)
            start_time_tz = datetime.now(tz=tz_object)
            print(f"Start time: {start_time.strftime("%Y-%m-%d %H:%M:%S")}")

            trial_num, trial_length, trial_users = trial

            log_db_filename = f"/tmp/trial_{trial_users}_{trial_length}_{trial_num}_{datetime.now().strftime('%Y%m%d%H%M%S')}.db"
            log_db_minio_filename = make_resource_trial_file_name(trial, log_extension)


            command_line = [
                "uv", "run", "locust", "-f", "locust_scripts/logging_sequential_end_to_end.py",
                "--host", host,
                "--headless", "-t", trial_length, "-u", trial_users,
                "--spawn-rate", trial_users, "--json", "--skip-log", "--only-summary", "--reset-stats",
                "--sqlite_db", log_db_filename, 
                "--loglevel", "ERROR", "BenchmarkUser"
            ]

            try:
                subprocess.run(command_line, check=True, stdout=subprocess.DEVNULL)
            except Exception as e:
                print(f"Error: {e}")
                
            end_time = datetime.now()
            end_time_tz = datetime.now(tz=tz_object)

            ssh.set_cpu_governor_to_performance(revert=True)    
            print(f"End time: {end_time.strftime("%Y-%m-%d %H:%M:%S")}")
            
            validate_environment_health_during_trial(start_time_tz, end_time_tz, prior_pod_restarts, tz="America/New_York")
            post_pod_conditions = get_pod_conditions(namespace="globeco", raise_exception_on_not_ready=False)
            if prior_pod_conditions != post_pod_conditions:
                print("Pod conditions changed during trial.  Skipping data collection.")
                continue
            minio_client.fput_object(log_bucket_name, log_db_minio_filename, log_db_filename)
            os.remove(log_db_filename)

            for metric, metric_bucket_name, metric_extension, calculate_rate in zip(metrics, metric_bucket_names, metric_extensions, calculate_rates):
                prom = prometheus.get_prometheus_connection()
                prometheus_data = prometheus.get_prometheus_data(prom, microservices, metric, start_time, end_time, calculate_rate=calculate_rate)
                filename = make_resource_trial_file_name(trial, metric_extension)
                prometheus_data.to_parquet(filename)
                minio_client.fput_object(metric_bucket_name, filename, filename)
                os.remove(filename)
            if collect_thermal_metrics:
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
            with open(error_log_name, "a") as f:
                number_of_errors += 1
                f.write(f"Error {number_of_errors} at {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n")
                f.write(f"Error in trial {trial}: {e}.\n{traceback.format_exc()}\n")
            continue
            
    ssh.set_cpu_governor_to_performance(revert=True)    




def main():
    parser = argparse.ArgumentParser(
        description="Run local calibration experiments"
    )

    parser.add_argument(
        "--host",
        type=str,
        required=True,
        default="http://globeco-portfolio-management-portal:3000",
        help="Host name and port"
    )
    
    parser.add_argument(
        "--bucket-name-prefix",
        type=str,
        required=True,
        help="Prefix for MinIO bucket names"
    )
    
    parser.add_argument(
        "--trial-numbers",
        type=int,
        nargs="+",
        default=None,
        help="List of trial numbers to run (default: None, runs all)"
    )
    
    parser.add_argument(
        "--users",
        type=int,
        nargs="+",
        default=None,
        help="List of user counts to test (default: None)"
    )
    
    parser.add_argument(
        "--resource-profile",
        type=str,
        default="default",
        help="Resource profile to use (default: default)"
    )
    
    parser.add_argument(
        "--trial-lengths-minutes",
        type=int,
        nargs="+",
        default=None,
        help="List of trial lengths in minutes (default: None)"
    )
    
    parser.add_argument(
        "--microservices",
        type=str,
        nargs="+",
        default=None,
        help="List of microservices to test (default: None, uses all)"
    )
    
    parser.add_argument(
        "--replicas",
        type=int,
        default=1,
        help="Number of replicas for each microservice (default: 1)"
    )
    
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="Skip environment validation (default: False)"
    )
    
    parser.add_argument(
        "--skip-initialization",
        action="store_true",
        help="Skip initialization (restarts and database truncation) (default: False)"
    )
    
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose output (default: False)"
    )
    
    parser.add_argument(
        "--collect-thermal-metrics",
        action="store_true",
        help="Collect thermal metrics (default: False)"
    )
    
    parser.add_argument(
        "--wait-for-cooling",
        action="store_true",
        help="Wait for system cooling before running trials (default: False)"
    )
    
    args = parser.parse_args()

    microservices = args.microservices
    if microservices is None:
        microservices = ['globeco-allocation-service', 'globeco-confirmation-service', 
                'globeco-execution-service', 
                'globeco-fix-engine', 'globeco-order-service', 
                'globeco-portfolio-accounting-service', 'globeco-portfolio-management-portal', 
                'globeco-portfolio-service', 'globeco-pricing-service', 'globeco-security-service',
                'globeco-trade-service', 'globeco-order-generation-service']

    print("Starting local calibration experiment with the following parameters:")
    print(f"Host: {args.host}")
    print(f"Bucket Name Prefix: {args.bucket_name_prefix}")
    print(f"Trial Numbers: {args.trial_numbers}")
    print(f"Users: {args.users}")
    print(f"Resource Profile: {args.resource_profile}")
    print(f"Trial Lengths (minutes): {args.trial_lengths_minutes}")
    print(f"Microservices: {microservices}")
    print(f"Replicas: {args.replicas}")
    print(f"Validate: {not args.no_validate}")
    print(f"Skip Initialization: {args.skip_initialization}")
    print(f"Verbose: {args.verbose}")
    print(f"Wait for Cooling: {args.wait_for_cooling}")
    print(f"Collect Thermal Metrics: {args.collect_thermal_metrics}")
    
    run(
        host=args.host,
        bucket_name_prefix=args.bucket_name_prefix,
        trial_numbers=args.trial_numbers,
        users=args.users,
        resource_profile=args.resource_profile,
        trial_lengths_minutes=args.trial_lengths_minutes,
        microservices=microservices,
        replicas=args.replicas,
        validate=not args.no_validate,
        verbose=args.verbose,
        overrides=None,
        wait_for_cooling_before_run=args.wait_for_cooling,
        skip_initialization=args.skip_initialization,
        collect_thermal_metrics=args.collect_thermal_metrics
    )

if __name__ == "__main__":
    main()

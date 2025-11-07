import subprocess
import time
import os
import random
from datetime import datetime, timedelta
import traceback

from minio import Minio

import ssh
import prometheus
from experiments.calibration.common import scale_microservice_deployments, wait_for_all_rollouts, parse_locust_output, \
    get_threshold_lookup, wait_for_cooling, file_count, file_exists, initialize_databases, \
    initialize_environments_for_trial, initialize_environments_for_resource_trial, validate_environments, \
    ensure_bucket_exists, save_to_minio, run_test_in_kubernetes
from experiments.calibration.constants import namespace, NODE_METRICS, eastern_tz


def run_test(tag, time_expression="5m", user_count="1", spawn_rate="1", verbose=False):
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

        # Parse the output to get the JSON data
        parsed_data = parse_locust_output(logs_result.stdout)

        # Clean up
        subprocess.run(["kubectl", "delete", "pod", pod_name, "-n", namespace])

        # Return results
        if parsed_data:
            if verbose:
                print("\n=== Parsed Data ===")
                for i, endpoint_data in enumerate(parsed_data):
                    print(f"Endpoint {i+1}: {endpoint_data['method']} {endpoint_data['name']}")
                    print(f"  Requests: {endpoint_data['num_requests']}")
                    print(f"  Failures: {endpoint_data['num_failures']}")
                    print(f"  Avg Response Time: {endpoint_data['total_response_time'] / max(endpoint_data['num_requests'], 1):.2f}ms")
                    print()

            return parsed_data
        else:
            # print(f"Could not parse JSON from output: {logs_result.stdout}")
            raise Exception(f"Could not parse JSON from output: {logs_result.stdout[:200]}")

    except Exception as e:
        print(f"Error: {e}")
        subprocess.run(["kubectl", "delete", "pod", pod_name])


def get_trials(selected_microservices, trial_numbers=[0, 1, 2, 3, 4, 5, 6, 7], trial_lengths=["2m"],
                trial_users=["20", "40", "60", "80", "100"],
                trial_cpus=["200m", "400m", "600m", "800m", "1000m"] ):

    return [(microservice, trial_num, trial_length, trial_user, trial_cpu) for microservice in selected_microservices
            for trial_num in trial_numbers
            for trial_length in trial_lengths
            for trial_user in trial_users
            for trial_cpu in trial_cpus]
    

def get_resource_trials(trial_numbers=list(range(30)), 
        trial_lengths=["10m"], trial_users=["50"]):
        return [(trial_num, trial_length, trial_user) 
            for trial_num in trial_numbers
            for trial_length in trial_lengths
            for trial_user in trial_users]


def make_file_name(trial):
    microservice, trial_num, trial_length, trial_workers, trial_cpu = trial
    return f"{microservice}_{trial_cpu}-{trial_workers}-{trial_length}-{trial_num}.txt"


def get_next_trial(minio_client, trials, bucket_name):

    # Check to see if we have already completed all trial
    if file_count(minio_client, bucket_name) >= len(trials):
        return None
    
    # If not, pick one that has not been completed
    while True:
        trial = random.choice(trials)
        filename = make_file_name(trial)
        if not file_exists(minio_client, bucket_name, filename):
            return trial

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
            filename = make_resource_trial_file_name(trial, extension)
            # If any file in the trial doesn't exist, we will rerun
            if not file_exists(minio_client, bucket_name, filename):
                return trial


def run_trial(trial):
    microservice, trial_num, trial_length, trial_users, trial_cpu = trial
    print(f"Running trial number {trial_num} for {trial_length} using {trial_users} users. {microservice} set at {trial_cpu}")
    raw_output = run_test_in_kubernetes(time_expression=trial_length, user_count=trial_users, spawn_rate=trial_users, verbose=False)
    return raw_output


def run_resource_trial(trial, verbose=False):
    trial_num, trial_length, trial_users = trial
    print(f"Running trial number {trial_num} for {trial_length} using {trial_users} users.")
    raw_output = run_test_in_kubernetes(time_expression=trial_length, user_count=trial_users, spawn_rate=trial_users, verbose=verbose)
    return raw_output


def run(bucket_name, replicas, selected_microservices, trial_numbers, trial_lengths, trial_users, trial_cpus):
    
    minio_client = Minio(
        "minio:9000",  
        access_key= os.environ['MINIO_ACCESS_KEY'],
        secret_key= os.environ['MINIO_SECRET_KEY'],
        secure=False  # Set to True for production with TLS
    )

    ensure_bucket_exists(minio_client, bucket_name)

    trials = get_trials(selected_microservices, trial_numbers=trial_numbers, 
    trial_lengths=trial_lengths, trial_users=trial_users, trial_cpus= trial_cpus)
    
    while trial := get_next_trial(minio_client, trials, bucket_name):
        try:
            scale_microservice_deployments(0)
            time.sleep(30) # Allow time for scale down
            initialize_databases()
            time.sleep(20) # Give databases time to stabilize
            initialize_environments_for_trial(trial, replicas=replicas)
            print("Environment Initialized.  Starting 30 second wait.")
            time.sleep(30) # It will take at least this long.  Waiting leaves time for stabilization.
            wait_for_all_rollouts()
            validate_environments()
            time.sleep(10) # Stabilization
            raw_output = run_trial(trial)
            filename = make_file_name(trial)
            save_to_minio(minio_client, raw_output, bucket_name, filename)
        except Exception as e:
            print(f"Error in trial {trial}: {e}")
            continue
    
        # scale_microservice_deployments(0)
        # initialize_databases()
        # initialize_environments_for_trial(trial, replicas=replicas)
        # print("Environment Initialized.  Starting 30 second wait.")
        # time.sleep(30) # It will take at least this long.  Waiting leaves time for stabilization.
        # wait_for_all_rollouts()
        # validate_environments(trial)
        # time.sleep(10) # Stabilization
        # raw_output = run_trial(trial)
        # filename = make_file_name(trial)
        # save_to_minio(minio_client, raw_output, bucket_name, filename)


        # break   #Temporary for testing    


def run_fixed_size(bucket_name, replicas, selected_microservices, trial_numbers, trial_lengths, trial_users, trial_cpus):
    # The purpose of this test is to find the maximum number of concurrent users
    
    minio_client = Minio(
        "minio:9000",  
        access_key= os.environ['MINIO_ACCESS_KEY'],
        secret_key= os.environ['MINIO_SECRET_KEY'],
        secure=False  # Set to True for production with TLS
    )

    ensure_bucket_exists(minio_client, bucket_name)

    trials = get_trials(["aggregate"], trial_numbers=trial_numbers, 
    trial_lengths=trial_lengths, trial_users=trial_users, trial_cpus= trial_cpus)
    
    threshold_lookup = get_threshold_lookup()


    while trial := get_next_trial(minio_client, trials, bucket_name):
        try:
            scale_microservice_deployments(0)
            initialize_databases()
            initialize_environments_for_resource_trial(replicas=replicas)
            print("Environment Initialized.  Starting 30 second wait.")
            time.sleep(30) # It will take at least this long.  Waiting leaves time for stabilization.
            wait_for_all_rollouts()
            # validate_environments(trial)
            time.sleep(10) # Stabilization
            print("Wait up to 5 minutes for cooling")
            wait_for_cooling(threshold_lookup)
            raw_output = run_trial(trial)
            filename = make_file_name(trial)
            save_to_minio(minio_client, raw_output, bucket_name, filename)
        except Exception as e:
            print(f"Error in trial {trial}: {e}.\n{traceback.format_exc()}")
            continue
    




def run_resource_utilization_sample(bucket_name_prefix, replicas, microservices, trial_numbers, trial_lengths, 
                                    trial_users, wait_for_cooling_before_run=False, validate=False,
                                     overrides=[]):
    
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
            trial_lengths=trial_lengths, 
            trial_users=trial_users)

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
            raw_output = run_resource_trial(trial)
            end_time = datetime.now()
            ssh.set_cpu_governor_to_performance(revert=True)    
            print(f"End time: {end_time.strftime("%Y-%m-%d %H:%M:%S")}")
            filename = make_resource_trial_file_name(trial, log_extension)
            save_to_minio(minio_client, raw_output, log_bucket_name, filename)
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

        # break   #Temporary for testing    


def run_baseline_idle_sample(bucket_name, num_trials, trial_length):
    
    minio_client = Minio(
        "minio:9000",  
        access_key= os.environ['MINIO_ACCESS_KEY'],
        secret_key= os.environ['MINIO_SECRET_KEY'],
        secure=False  # Set to True for production with TLS
    )
    
    ensure_bucket_exists(minio_client, bucket_name)

    start_time = datetime(2025, 10, 16, 20, 47, 39, tzinfo=eastern_tz)

    for i in range(num_trials):
        end_time = start_time + timedelta(minutes=trial_length)
        # trial = (i, f"{trial_length}m", "0")
        trial_success = False
        fail_count = 0
        while not trial_success:
            try:
                for node, node_metrics in NODE_METRICS.items():
                    for metric in node_metrics:
                        prom = prometheus.get_prometheus_connection()
                        prometheus_data = prometheus.get_prometheus_node_data(prom, node, metric, start_time, end_time, verbose=False)
                        filename = f"trial-{i}-idle-{node}-{metric}.parquet"
                        prometheus_data.to_parquet(filename)
                        minio_client.fput_object(bucket_name, filename, filename)
                        os.remove(filename)
                trial_success = True
            except Exception as e:
                print(f"Error in trial {i}: {e}.\n{traceback.format_exc()}")
                fail_count += 1
                if fail_count >= 5:
                    print(f"Trial {i} failed 5 times.  Skipping.")
                    break
                print(f"Retrying trial {i} after 10 seconds.")
                time.sleep(10)

        print(f"Completed idle trial {i} from {start_time} to {end_time}")                
        start_time = end_time + timedelta(minutes=2, seconds=30)  # 2 minute 30 second gap between trials
                




if __name__ == "__main__": 

    # Excluding globeco-order-generation-service from the calibration due to its unique nature.  Fixed at 2000m.
    selected_microservices = ['globeco-allocation-service', 'globeco-confirmation-service', 
                 'globeco-execution-service', 
                 'globeco-fix-engine', 'globeco-order-service', 
                 'globeco-portfolio-accounting-service', 'globeco-portfolio-management-portal', 
                 'globeco-portfolio-service', 'globeco-pricing-service', 'globeco-security-service',
                 'globeco-trade-service']
    
    microservices = selected_microservices + ['globeco-order-generation-service']

    experiment = 4 # Change this value to select the experiment to run

    # The following was abandoned in favor of run_resource_utilization_sample with modifications
    # run_fixed_size(bucket_name="experiment-2-20251021-raw", replicas=1, selected_microservices=selected_microservices, 
    #     trial_numbers=list(range(30)), trial_lengths=["10m"], 
    #     trial_users=["25", "50", "75", "100"],
    #     trial_cpus=["1000m"] )
        
    # The following runs were used for experiment 1 calibration data collection.
    if experiment == 1:
        run_resource_utilization_sample(bucket_name_prefix="calibration-20251013", 
            replicas=1, 
            microservices=microservices,
            trial_numbers=list(range(200)), trial_lengths=["10m"], 
            trial_users=["50"])

    
    # The following runs provided the idle baseline data for experiment 1
    # run_baseline_idle_sample("calibration-20251019-idle", 200, 10)
    
    # The following run provides data for expermient 2
    if experiment == 2: 
        run_resource_utilization_sample(bucket_name_prefix="experiment-2-20251025", 
            replicas=1, 
            microservices=microservices,
            trial_numbers=list(range(30)), trial_lengths=["10m"], 
            trial_users=["25", "50", "75", "100"],
            wait_for_cooling_before_run=True)
    
    # The following run provides data for expermient 3
    if experiment == 3:
        run_resource_utilization_sample(bucket_name_prefix="experiment-3-20251026", 
            replicas=1, 
            microservices=microservices,
            trial_numbers=list(range(200)), trial_lengths=["10m"], 
            trial_users=["75"],
            wait_for_cooling_before_run=True)

    # The following run provides data for expermient 4

    # Original overrides for experiment 4
    # This is experiment B in the report.  It was modified from the original non-woring experiment A
    overrides_b = [
        {'globeco-allocation-service': {'cpu_request': '100m', 'cpu_limit': '100m', 
                                        'memory_request': '100Mi', 'memory_limit': '100Mi'}},
        {'globeco-confirmation-service': {'cpu_request': '100m', 'cpu_limit': '100m',
                                          'memory_request': '100Mi', 'memory_limit': '100Mi'}},
        {'globeco-execution-service': {'cpu_request': '300m', 'cpu_limit': '300m',
                                       'memory_request': '900Mi', 'memory_limit': '900Mi'}},
        {'globeco-fix-engine': {'cpu_request': '100m', 'cpu_limit': '100m',
                                'memory_request': '100Mi', 'memory_limit': '100Mi'}},
        {'globeco-order-generation-service': {'cpu_request': '500m', 'cpu_limit': '500m',
                                   'memory_request': '700Mi', 'memory_limit': '700Mi'}},
        {'globeco-order-service': {'cpu_request': '400m', 'cpu_limit': '400m',
                                   'memory_request': '1100Mi', 'memory_limit': '1100Mi'}},
        {'globeco-portfolio-accounting-service': {'cpu_request': '100m', 'cpu_limit': '100m',
                                                  'memory_request': '100Mi', 'memory_limit': '100Mi'}},
        {'globeco-portfolio-management-portal': {'cpu_request': '200m', 'cpu_limit': '200m',
                                                  'memory_request': '200Mi', 'memory_limit': '200Mi'}},
        {'globeco-portfolio-service': {'cpu_request': '100m', 'cpu_limit': '100m',
                                       'memory_request': '200Mi', 'memory_limit': '200Mi'}},
        {'globeco-pricing-service': {'cpu_request': '300m', 'cpu_limit': '300m',
                                     'memory_request': '1000Mi', 'memory_limit': '1000Mi'}},
        {'globeco-security-service': {'cpu_request': '100m', 'cpu_limit': '100m',
                                       'memory_request': '200Mi', 'memory_limit': '200Mi'}},
        {'globeco-trade-service': {'cpu_request': '400m', 'cpu_limit': '400m',
                                   'memory_request': '1000Mi', 'memory_limit': '1000Mi'}}
    ]

    # This is a non-named experiment.
    # Modified overrides for experiment 4 with increased resources for the order generation service
    overrides = [
        {'globeco-allocation-service': {'cpu_request': '100m', 'cpu_limit': '100m', 
                                        'memory_request': '100Mi', 'memory_limit': '100Mi'}},
        {'globeco-confirmation-service': {'cpu_request': '100m', 'cpu_limit': '100m',
                                          'memory_request': '100Mi', 'memory_limit': '100Mi'}},
        {'globeco-execution-service': {'cpu_request': '300m', 'cpu_limit': '300m',
                                       'memory_request': '900Mi', 'memory_limit': '900Mi'}},
        {'globeco-fix-engine': {'cpu_request': '100m', 'cpu_limit': '100m',
                                'memory_request': '100Mi', 'memory_limit': '100Mi'}},
        {'globeco-order-generation-service': {'cpu_request': '1', 'cpu_limit': '1',
                                   'memory_request': '700Mi', 'memory_limit': '700Mi'}},
        {'globeco-order-service': {'cpu_request': '400m', 'cpu_limit': '400m',
                                   'memory_request': '1100Mi', 'memory_limit': '1100Mi'}},
        {'globeco-portfolio-accounting-service': {'cpu_request': '100m', 'cpu_limit': '100m',
                                                  'memory_request': '100Mi', 'memory_limit': '100Mi'}},
        {'globeco-portfolio-management-portal': {'cpu_request': '200m', 'cpu_limit': '200m',
                                                  'memory_request': '200Mi', 'memory_limit': '200Mi'}},
        {'globeco-portfolio-service': {'cpu_request': '100m', 'cpu_limit': '100m',
                                       'memory_request': '200Mi', 'memory_limit': '200Mi'}},
        {'globeco-pricing-service': {'cpu_request': '300m', 'cpu_limit': '300m',
                                     'memory_request': '1000Mi', 'memory_limit': '1000Mi'}},
        {'globeco-security-service': {'cpu_request': '100m', 'cpu_limit': '100m',
                                       'memory_request': '200Mi', 'memory_limit': '200Mi'}},
        {'globeco-trade-service': {'cpu_request': '400m', 'cpu_limit': '400m',
                                   'memory_request': '1000Mi', 'memory_limit': '1000Mi'}}
    ]


    # This is a non-named experiment.
    # A Modified overrides for experiment 4 with increased resources for the pricing service (also includes pricing service)
    overrides = [
        {'globeco-allocation-service': {'cpu_request': '100m', 'cpu_limit': '100m', 
                                        'memory_request': '100Mi', 'memory_limit': '100Mi'}},
        {'globeco-confirmation-service': {'cpu_request': '100m', 'cpu_limit': '100m',
                                          'memory_request': '100Mi', 'memory_limit': '100Mi'}},
        {'globeco-execution-service': {'cpu_request': '300m', 'cpu_limit': '300m',
                                       'memory_request': '900Mi', 'memory_limit': '900Mi'}},
        {'globeco-fix-engine': {'cpu_request': '100m', 'cpu_limit': '100m',
                                'memory_request': '100Mi', 'memory_limit': '100Mi'}},
        {'globeco-order-generation-service': {'cpu_request': '1', 'cpu_limit': '1',
                                   'memory_request': '700Mi', 'memory_limit': '700Mi'}},
        {'globeco-order-service': {'cpu_request': '400m', 'cpu_limit': '400m',
                                   'memory_request': '1100Mi', 'memory_limit': '1100Mi'}},
        {'globeco-portfolio-accounting-service': {'cpu_request': '100m', 'cpu_limit': '100m',
                                                  'memory_request': '100Mi', 'memory_limit': '100Mi'}},
        {'globeco-portfolio-management-portal': {'cpu_request': '200m', 'cpu_limit': '200m',
                                                  'memory_request': '200Mi', 'memory_limit': '200Mi'}},
        {'globeco-portfolio-service': {'cpu_request': '100m', 'cpu_limit': '100m',
                                       'memory_request': '200Mi', 'memory_limit': '200Mi'}},
        {'globeco-pricing-service': {'cpu_request': '600m', 'cpu_limit': '600m',
                                     'memory_request': '1000Mi', 'memory_limit': '1000Mi'}},
        {'globeco-security-service': {'cpu_request': '100m', 'cpu_limit': '100m',
                                       'memory_request': '200Mi', 'memory_limit': '200Mi'}},
        {'globeco-trade-service': {'cpu_request': '400m', 'cpu_limit': '400m',
                                   'memory_request': '1000Mi', 'memory_limit': '1000Mi'}}
    ]

 
    # This is a non-named experiment
    # Modified overrides for experiment 4 with increased resources for the security, execution, and order service
    overrides = [
        {'globeco-allocation-service': {'cpu_request': '100m', 'cpu_limit': '100m', 
                                        'memory_request': '100Mi', 'memory_limit': '100Mi'}},
        {'globeco-confirmation-service': {'cpu_request': '100m', 'cpu_limit': '100m',
                                          'memory_request': '100Mi', 'memory_limit': '100Mi'}},
        {'globeco-execution-service': {'cpu_request': '600m', 'cpu_limit': '600m',
                                       'memory_request': '900Mi', 'memory_limit': '900Mi'}},
        {'globeco-fix-engine': {'cpu_request': '100m', 'cpu_limit': '100m',
                                'memory_request': '100Mi', 'memory_limit': '100Mi'}},
        {'globeco-order-generation-service': {'cpu_request': '1', 'cpu_limit': '1',
                                   'memory_request': '700Mi', 'memory_limit': '700Mi'}},
        {'globeco-order-service': {'cpu_request': '800m', 'cpu_limit': '800m',
                                   'memory_request': '1100Mi', 'memory_limit': '1100Mi'}},
        {'globeco-portfolio-accounting-service': {'cpu_request': '100m', 'cpu_limit': '100m',
                                                  'memory_request': '100Mi', 'memory_limit': '100Mi'}},
        {'globeco-portfolio-management-portal': {'cpu_request': '200m', 'cpu_limit': '200m',
                                                  'memory_request': '200Mi', 'memory_limit': '200Mi'}},
        {'globeco-portfolio-service': {'cpu_request': '100m', 'cpu_limit': '100m',
                                       'memory_request': '200Mi', 'memory_limit': '200Mi'}},
        {'globeco-pricing-service': {'cpu_request': '600m', 'cpu_limit': '600m',
                                     'memory_request': '1000Mi', 'memory_limit': '1000Mi'}},
        {'globeco-security-service': {'cpu_request': '300m', 'cpu_limit': '300m',
                                       'memory_request': '200Mi', 'memory_limit': '200Mi'}},
        {'globeco-trade-service': {'cpu_request': '400m', 'cpu_limit': '400m',
                                   'memory_request': '1000Mi', 'memory_limit': '1000Mi'}}
    ]

    # C Recalculated overrides based on 99th percentile of raw CPU usage from experiment 3
    overrides = [
        {'globeco-allocation-service': {'cpu_request': '100m', 'cpu_limit': '100m', 
                                        'memory_request': '100Mi', 'memory_limit': '100Mi'}},
        {'globeco-confirmation-service': {'cpu_request': '100m', 'cpu_limit': '100m',
                                          'memory_request': '100Mi', 'memory_limit': '100Mi'}},
        {'globeco-execution-service': {'cpu_request': '500m', 'cpu_limit': '500m',
                                       'memory_request': '900Mi', 'memory_limit': '900Mi'}},
        {'globeco-fix-engine': {'cpu_request': '100m', 'cpu_limit': '100m',
                                'memory_request': '100Mi', 'memory_limit': '100Mi'}},
        {'globeco-order-generation-service': {'cpu_request': '1', 'cpu_limit': '1',
                                   'memory_request': '700Mi', 'memory_limit': '700Mi'}},
        {'globeco-order-service': {'cpu_request': '1', 'cpu_limit': '1',
                                   'memory_request': '1100Mi', 'memory_limit': '1100Mi'}},
        {'globeco-portfolio-accounting-service': {'cpu_request': '100m', 'cpu_limit': '100m',
                                                  'memory_request': '100Mi', 'memory_limit': '100Mi'}},
        {'globeco-portfolio-management-portal': {'cpu_request': '500m', 'cpu_limit': '500m',
                                                  'memory_request': '200Mi', 'memory_limit': '200Mi'}},
        {'globeco-portfolio-service': {'cpu_request': '200m', 'cpu_limit': '200m',
                                       'memory_request': '200Mi', 'memory_limit': '200Mi'}},
        {'globeco-pricing-service': {'cpu_request': '1', 'cpu_limit': '1',
                                     'memory_request': '1000Mi', 'memory_limit': '1000Mi'}},
        {'globeco-security-service': {'cpu_request': '200m', 'cpu_limit': '200m',
                                       'memory_request': '200Mi', 'memory_limit': '200Mi'}},
        {'globeco-trade-service': {'cpu_request': '900m', 'cpu_limit': '900m',
                                   'memory_request': '1000Mi', 'memory_limit': '1000Mi'}}
    ]


# D Recalculated overrides based on 99.99th percentile of raw CPU usage from experiment 3 plus 100m buffer
    overrides = [
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



    # experiment-4-20251029a with increased resources for order generation and pricing service
    # experiment-4-20251029b with increased resources for execution, order, and security services

    if experiment == 4:
        run_resource_utilization_sample(bucket_name_prefix="experiment-4-20251029b", 
            replicas=1, 
            microservices=microservices,
            trial_numbers=list(range(100)), trial_lengths=["10m"], 
            trial_users=["75"],
            wait_for_cooling_before_run=True,
            validate=True,
            overrides=overrides_b)
         
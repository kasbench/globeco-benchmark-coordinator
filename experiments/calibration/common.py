import json
import os
import pickle
import re
import subprocess
import tempfile
import time
from collections import defaultdict

import kr8s
from kr8s.objects import StatefulSet
from minio import S3Error, Minio

from constants import namespace, microservices


minio_client = Minio(
        "minio:9000",
        access_key= os.environ['MINIO_ACCESS_KEY'],
        secret_key= os.environ['MINIO_SECRET_KEY'],
        secure=False  # Set to True for production with TLS
    )

def get_pods():
    return kr8s.get("pods", namespace=namespace)


def get_microservice_pods():
    for pod in get_pods():
        for microservice in microservices:
            pattern = microservice + r"-\S{9,10}-\S{5}"
            if re.search(pattern, pod.name):
                yield pod


def get_deployments():
    return kr8s.get("deployments", namespace=namespace)


def get_microservice_deployments():
    return (deployment for deployment in get_deployments()
                if deployment. name in microservices)


def scale_microservice_deployments(scale):
    for deployment in get_microservice_deployments():
        deployment.scale(scale)


def get_deployment_containers(deployment):
    return deployment['spec']['template']['spec']['containers']


def patch_allocation(deployment, cpu_request, cpu_limit, memory_request, memory_limit):
    container = get_deployment_containers(deployment)[0]

    spec = deployment.spec

    for container in spec['template']['spec']['containers']:
        if container['name'] == container.name:
            # 4. Modify the resources dictionary for this container
            container['resources'] = {
                'requests': {
                    'cpu': cpu_request,
                    'memory': memory_request
                },
                'limits': {
                    'cpu': cpu_limit,
                    'memory': memory_limit
                }
            }
            break

    patch = {"spec": {"template": spec['template']}}

    deployment.patch(patch)


def wait_for_rollout(deployment, timeout_seconds=300, verbose=True):
    """
    Wait for a Deployment rollout to complete, similar to `kubectl rollout status`.
    """
    start_time = time.time()
    name = deployment.name

    # The following line is required.  Refresh alone does not work.  Might just be timing.
    deployment = list(kr8s.get("Deployment", name, namespace=namespace))[0]

    while True:
        if time.time() - start_time > timeout_seconds:
            raise TimeoutError(f"Timed out waiting for deployment '{name}' to roll out.")

        retries = 3
        for i in range(retries):
            try:
                deployment.refresh()  # Refresh the object from the API
            except Exception as e:
                if i == retries - 1:
                    raise(e)
                print(f"Exception in waiting for deployment: {e}.  Retrying")
                time.sleep(15)
        status = deployment.status or {}
        conditions = {c["type"]: c for c in status.get("conditions", [])}

        progressing = conditions.get("Progressing", {})
        available = conditions.get("Available", {})

        # Print a status line for debugging
        updated = status.get("updatedReplicas", 0)
        ready = status.get("readyReplicas", 0)
        desired = deployment.spec.get("replicas", 0)
        if verbose:
            print(f"Waiting for rollout of {name}: {ready}/{desired} ready, {updated} updated")

        # Success: progressing=True, available=True, and all replicas ready
        if (progressing.get("status") == "True" and progressing.get("reason") == "NewReplicaSetAvailable"
            and available.get("status") == "True"
            and ready == desired):
            if verbose:
                print(f"Deployment '{name}' successfully rolled out.")
            return

        # Failure case (like kubectl does)
        if progressing.get("status") == "False" and progressing.get("reason") == "ProgressDeadlineExceeded":
            raise RuntimeError(f"Rollout of deployment '{name}' failed: ProgressDeadlineExceeded")

        time.sleep(10)


def wait_for_all_rollouts():
    for deployment in get_microservice_deployments():
        try:
            wait_for_rollout(deployment)
        except Exception as e:
            print(f"Exception in waiting for deployment: {e}.  Retrying")
            time.sleep(15)


def set_default_state_for_deployment(deployment, cpu="1000m", wait=True, verbose=False):
    if deployment.name in ['globeco-order-service', 'globeco-trade-service', 'globeco-pricing-service']:
        memory = ('200Mi', '2000Mi')
    else:
        memory = ('256Mi', '1024Mi')
    patch_allocation(deployment, "1000m", "1000m", memory[0], memory[1])

    time.sleep(5)

    if wait:
        wait_for_rollout(deployment, verbose=verbose)


def set_default_state_all_microservice_deployments(wait=True, verbose=False):
    # Get microservice deployments
    deployments = get_microservice_deployments()

    # Set all microservices to default CPU and memory
    for deployment in deployments:
        set_default_state_for_deployment(deployment, wait=False)

    time.sleep(5)

    deployments = get_microservice_deployments()

    for deployment in deployments:
        wait_for_rollout(deployment, verbose=verbose)


def parse_locust_output(output_string):
    """ This parses the JSON output provided by Locust from other errors in the log.  This seems
    to be adequate in most cases, but would fail on errors containing JSON-like output.  May need to
    revisit."""
    # Method 1: Extract JSON using regex (most reliable)
    json_match = re.search(r'(\[[\s\S]*\])', output_string)
    if json_match:
        json_str = json_match.group(1)
        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            print(f"JSON decode error: {e}")
            return None

    # Method 2: If regex fails, try to find start and end of JSON
    start = output_string.find('[')
    end = output_string.rfind(']') + 1

    if start != -1 and end != 0:
        json_str = output_string[start:end]
        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            print(f"JSON decode error: {e}")
            return None

    return None


def get_threshold_lookup(file="./threshold_lookup.pkl"):
    if os.path.exists(file):
        with open(file, "rb") as f:
            threshold_lookup = pickle.load(f)
            for (node, metric), value in threshold_lookup.items():
                threshold_lookup[(node, metric)] = float(value)
        return threshold_lookup
    else:
        return None


def wait_for_cooling(threshold_lookup, max_wait_seconds=600):
    completed_node_metrics = []
    start_time  = time.time()
    while True:

        request = defaultdict(list)
        for (node, metric), value in threshold_lookup.items():
            if (node, metric) not in completed_node_metrics:
                request[node].append(metric)
                # print(f"Still need {metric} for {node}")
        if len(request) == 0:  # This should never happen here, since we check at the end of the loop
            return

        print(f"Requesting thermal metrics for: {dict(request)}")
        results = thermal_metrics_collector.get_thermals_for_request(request)
        print(f"Thermal results: {results}")

        for result in results:
            node, _ , metrics = result
            if node == "server":
                continue
            for metric, value in metrics.items():
                metric = metric.replace("-", "_")
                if metric in ["acpitz_acpi_0", "nvme_pci_0100", "nvme_pci_10100"]:      # Excluding
                    continue
                if value <= threshold_lookup[(node, metric)]:
                    completed_node_metrics.append((node, metric))
                else:
                    print(f"Node {node} metric {metric} value {value} not below threshold {threshold_lookup[(node, metric)]}")

        # Check if all node-metrics have completed
        request = defaultdict(list)
        for (node, metric), value in threshold_lookup.items():
            if (node, metric) not in completed_node_metrics:
                request[node].append(metric)
                # print(f"Still need {metric} for {node}")
        if len(request) == 0:
            return

        if time.time() - start_time > max_wait_seconds:
            raise TimeoutError("Timed out waiting for cooling to complete.")
        print("Sleeping for 15 seconds (waitng for cooling)")
        time.sleep(15)


def get_default_microservice_states():
    default_states = {}
    for microservice in  microservices:
        if microservice in ['globeco-order-service', 'globeco-trade-service', 'globeco-pricing-service']:
            memory = ('256Mi', '2000Mi')
        else:
            memory = ('256Mi', '1024Mi')
        default_states[microservice] = {"cpu_request": "1000m", "cpu_limit": "1000m",
            "memory_request": memory[0], "memory_limit" :memory[1]}

    return default_states


def get_microservice_states(overrides):
    # print(f"Overrides: {overrides}")
    states = get_default_microservice_states()

    for override in overrides:
        for microservice, override_detail in override.items():
            for key, value in override_detail.items():
                if key not in ["cpu_request", "cpu_limit", "memory_request", "memory_limit"]:
                    raise ValueError(f"Invalid key: {key}")
                states[microservice][key] = value

    return states


def cpu_add(original_cpu, additional_cpu):
    original_value = int(original_cpu[:-1])
    additional_value = int(additional_cpu[:-1])
    return f"{original_value + additional_value}m"


def file_count(minio_client, bucket_name):
    files = minio_client.list_objects(bucket_name, recursive=True)
    return sum(1 for _ in files)


def file_exists(minio_client, bucket_name, filename):
    try:
        minio_client.stat_object(bucket_name, filename)
        return True
    except S3Error as err:
        if err.code == "NoSuchKey":
            return False
        else:
            print(f"An S3 error occurred: {err}")
            return False
    except Exception as err:
        print(f"An unexpected error occurred: {err}")
        return False


def restore_postgres(service_name):
    print(f"Restoring {service_name}")
    pg_restore_command = [
    "/usr/bin/pg_restore",
    "-U", "postgres",
    "-d", "postgres",
    "-Ft",
    "/var/lib/postgresql/data/backups/pre-callibration-backup.tar",
    "--clean",
    "-v"
    ]

    # The full subprocess command
    full_command = [
        "kubectl",
        "exec",
        f"svc/{service_name}",
        "-c", service_name,
        "-n", "globeco",
        "--",
    ] + pg_restore_command

    # Execute the command
    result = subprocess.run(full_command, capture_output=True, text=True, check=False)
    if result.returncode:
        raise Exception(f"Return code {result.returncode} in {service_name} restore. {result.stderr} - {result.stdout}")


def restore_mongo(service_name):
    print(f"Restoring {service_name}")
    mongo_restore_command = [
    "/usr/bin/mongorestore",
    "--drop", "/data/db/backups/pre-callibration-backup"
    ]

    # The full subprocess command
    full_command = [
        "kubectl",
        "exec",
        f"svc/{service_name}",
        "-n", "globeco",
        "--",
    ] + mongo_restore_command

    # Execute the command
    result = subprocess.run(full_command, capture_output=True, text=True, check=False)
    if result.returncode:
        raise Exception(f"Return code {result.returncode} in {service_name} restore. {result.stderr} - {result.stdout}")


def flush_redis(service_name):
    print(f"Flushing {service_name}")
    full_command = [
        "kubectl",
        "exec",
        f"svc/{service_name}",
        "-n", "globeco",
        "--",
        "/usr/local/bin/redis-cli",
        "FLUSHALL"
    ]

    # Execute the command
    result = subprocess.run(full_command, capture_output=True, text=True, check=False)
    if result.returncode:
        raise Exception(f"Return code {result.returncode} in {service_name} restore. {result.stderr} - {result.stdout}")


def clean_data(data_path, node_name):
    print(f"[INFO] Cleaning data directory {data_path} on {node_name}...")

    clean_command = [
        "kubectl", "debug", f"node/{node_name}",
        "-it", "--image=busybox",  "--",
        "sh", "-c",
        f"rm -rf /host{data_path}/* /host{data_path}/.[!.]* 2>/dev/null || true; "
        # f"mkdir -p /host{data_path}; "
        # f"chown -R 1000:1000 /host{data_path}; "
        f"echo '{data_path}cleaned on {node_name}'"
    ]

    # Run the debug command
    result = subprocess.run(clean_command, capture_output=True, text=True, timeout=60)

    if result.returncode == 0:
        print("[SUCCESS] Data directory cleaned")
    else:
        print(f"[WARNING] Directory clean may have failed: {result.stderr}")


def scale_statefulset(service_name, replicas, namespace="globeco"):
    ss = StatefulSet.get(service_name, namespace)
    ss.scale(replicas)


def clean_postgres(service_name, service_path, node_name):

    # Scale node to 0 replicas
    scale_statefulset(service_name, 0)

    # Clean the data directory
    clean_data(f"/mnt/disk1/{service_path}/pgdata", node_name)

    # Scale node back to 1 replica
    scale_statefulset(service_name, 1)


def clean_mongo(service_name, service_path, node_name):

    # Scale node to 0 replicas
    scale_statefulset(service_name, 0)

    # Clean the data directory
    clean_data(f"/mnt/disk1/{service_path}", node_name)

    # Scale node back to 1 replica
    scale_statefulset(service_name, 1)


def initialize_databases():
    # globeco-execution-service-kafka
    kafka_reinit_simple.simple_kafka_reinit()

    # globeco-allocation-service-postgresql
    # restore_postgres("globeco-allocation-service-postgresql")
    clean_postgres("globeco-allocation-service-postgresql", "postgres-allocation-service", "node-3")

    # globeco-execution-service-postgresql
    # restore_postgres("globeco-execution-service-postgresql")
    clean_postgres("globeco-execution-service-postgresql", "postgres-execution-service", "node-4")

    # globeco-fix-engine-postgresql
    # restore_postgres("globeco-fix-engine-postgresql")
    clean_postgres("globeco-fix-engine-postgresql", "fix-engine-postgres", "node-0")

    # globeco-order-generation-service-mongodb
    # restore_mongo("globeco-order-generation-service-mongodb")
    clean_mongo("globeco-order-generation-service-mongodb", "mongodb-order-generation-service", "node-5")

    # globeco-order-generation-service-redis
    flush_redis("globeco-order-generation-service-redis")

    # globeco-order-service-postgresql
    clean_postgres("globeco-order-service-postgresql", "postgres-order-service", "node-5")

    # globeco-portfolio-accounting-service-postgresql
    # restore_postgres("globeco-portfolio-accounting-service-postgresql")
    clean_postgres("globeco-portfolio-accounting-service-postgresql", "postgres-portfolio-accounting-service", "node-2")

    # globeco-portfolio-accounting-service-redis
    flush_redis("globeco-portfolio-accounting-service-redis")

    # globeco-portfolio-service-mongodb
    # restore_mongo("globeco-portfolio-service-mongodb")
    clean_mongo("globeco-portfolio-service-mongodb", "portfolio-service-mongodb", "node-0")

    # globeco-trade-service-postgresql
    # restore_postgres("globeco-trade-service-postgresql")
    clean_postgres("globeco-trade-service-postgresql", "postgres-trade-service", "node-4")

    # Pause for database and Kafka rollouts.  Kafka is the slowest.
    time.sleep(22)

    # cleanup node debugger pods.
    kafka_reinit_simple.delete_node_debugger_pods()


def set_state(states, replicas):
    deployments = get_microservice_deployments()
    for deployment in deployments:
        patch_allocation(deployment, states[deployment.name]["cpu_request"],
                         states[deployment.name]["cpu_limit"],
                         states[deployment.name]["memory_request"],
                         states[deployment.name]["memory_limit"])
        deployment.scale(replicas)


def initialize_environments_for_trial(trial,  replicas=1):
    microservice, trial_num, trial_length, trial_users, trial_cpu = trial
    print(f"Initializing environments for trial number {trial_num} for {trial_length} using {trial_users} users. {microservice} set at {trial_cpu}")
    # override the default state with the trial parameters
    states = get_microservice_states([{microservice: {"cpu_request": trial_cpu, "cpu_limit": trial_cpu}}])
    set_state(states, replicas)


def initialize_environments_for_resource_trial(replicas=1, overrides=[]):
    states = get_microservice_states(overrides)
    set_state(states, replicas)


def cpu_equal(cpu1, cpu2):
    if cpu1 == cpu2:
        return True
    if cpu1 == "1000m" and cpu2 == "1":
        return True
    if cpu1 == "1" and cpu2 == "1000m":
        return True
    return False


def make_override_dict(overrides):
    override_dict = {}
    for override in overrides:
        for microservice, override_detail in override.items():
            override_dict[microservice] = override_detail
    return override_dict


def validate_environments(overrides=[]):

    overrides_dict = make_override_dict(overrides)
    for deployment in get_microservice_deployments():
        spec = deployment.spec
        microservice = deployment.name
        for container in spec['template']['spec']['containers']:
            if container.name == microservice:
                print(f"Validating {container.name}")
                resources = container['resources']
                print(f"Resources: {resources}")
                requests = resources['requests']
                limits = resources['limits']

                assert requests['cpu'] == overrides_dict[microservice]["cpu_request"], \
                    f"CPU request does not match for {container['name']}. Expected {overrides_dict[microservice]['cpu_request']}, got {requests['cpu']}"
                assert limits['cpu'] == overrides_dict[microservice]["cpu_limit"], \
                    f"CPU limit does not match for {container['name']}. Expected {overrides_dict[microservice]['cpu_limit']}, got {limits['cpu']}"
                assert requests['memory'] == overrides_dict[microservice]["memory_request"], \
                    f"Memory request does not match for {container['name']}. Expected {overrides_dict[microservice]['memory_request']}, got {requests['memory']}"
                assert limits['memory'] == overrides_dict[microservice]["memory_limit"], \
                    f"Memory limit does not match for {container['name']}. Expected {overrides_dict[microservice]['memory_limit']}, got {limits['memory']}"


def ensure_bucket_exists(client: Minio, bucket_name: str):
    """
    Creates a new bucket if it doesn't exist.

    Args:
        client: An initialized Minio client instance.
        bucket_name: The name of the bucket to create.

    Raises:
        S3Error: If the bucket creation fails for any reason other than
                 the bucket already existing.
    """
    try:
        client.make_bucket(bucket_name)
        print(f"Bucket '{bucket_name}' created successfully.")
    except S3Error as e:
        if e.code == "BucketAlreadyOwnedByYou" or e.code == "BucketAlreadyExists":
            print(f"Bucket '{bucket_name}' already exists.")
        else:
            print(f"Error creating bucket '{bucket_name}': {e}")
            raise # Re-raise the exception for other errors


def save_to_minio(minio_client, output, bucket_name, filename):
    print(f"Saving {bucket_name}/{filename}")
    with tempfile.NamedTemporaryFile(mode='w+', delete=True) as tmp:
        tmp.write(output)
        minio_client.fput_object(bucket_name, filename, tmp.name)


def run_test_in_kubernetes(time_expression="5m", user_count="1", spawn_rate="1", verbose=False):
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

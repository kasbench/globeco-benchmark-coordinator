import re
import subprocess
import time
import json
import os

import kr8s


microservices = ['globeco-allocation-service', 'globeco-confirmation-service', 'globeco-execution-service', 
                 'globeco-fix-engine', 'globeco-order-generation-service', 'globeco-order-service', 
                 'globeco-portfolio-accounting-service', 'globeco-portfolio-management-portal', 
                 'globeco-portfolio-service', 'globeco-pricing-service', 'globeco-security-service',
                 'globeco-trade-service']

namespace="globeco"

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


def wait_for_rollout(deployment, timeout_seconds=600, verbose=False):
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
                print(f"Exception: {e}.  Retrying")
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
            print(f"Waiting for rollout: {ready}/{desired} ready, {updated} updated")

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


if __name__ == "__main__": 

    NUM_RUNS = 30
    LENGTH = "2m"

    for run_number in range(NUM_RUNS):

        # Make sure all are scaled to 1 replica each
        scale_microservice_deployments(1)

        time.sleep(5)

        # Get iterator

        deployments = get_microservice_deployments()

        # Gather calibration data for each deployment
        for deployment in deployments:

            print(f"Deployment: {deployment.name}")

            set_default_state_all_microservice_deployments(wait=True)

            for cpu in range(200, 1001, 200):
                for users in range(20, 101, 20):
                    filename = f"./calibration-output/{deployment.name}_{cpu}-{users}-{LENGTH}-{run_number}.json"
                    if os.path.exists(filename) and os.path.getsize(filename) > 1000:
                        continue

                    print(f"Starting run for file {filename}")

                    # set CPU and memory requests and limits
                    set_default_state_for_deployment(deployment, cpu=cpu, wait=True, verbose=False)

                    # run the test
                    max_runs = 3
                    while max_runs:
                        try:
                            result = run_test(deployment.name, time_expression=LENGTH, user_count=str(users), spawn_rate=str(users))

                            # save to a file
                            with open(filename, "w") as f:
                                json.dump(result, f, indent=4)
                            break
                        except Exception as e:
                            max_runs -= 1
                            print(f"error: {e}")
                            if max_runs:
                                # sleeping to allow time for recovery
                                time.sleep(90)
                            else:
                                print(f"ERROR: skipping {filename} for {cpu} cpu and {users} users")

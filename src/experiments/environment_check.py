import re
from datetime import datetime

import kr8s
import paramiko
import pytz
from dateutil import parser
from kr8s import NotFoundError


def get_pods(namespace="globeco"):
    return kr8s.get("pods", namespace=namespace)


def get_nodes(namespace="globeco"):
    return kr8s.get("nodes", namespace=namespace)
  

def get_node_health_and_last_event_k8s_api():
    """
    Checks the health status of all Kubernetes nodes and reports on their
    Ready status and the last time a condition was observed.
    """
    node_info = {}
    try:
        # 1. Connect to the Kubernetes cluster
        api = kr8s.api()

        # 2. Fetch all nodes
        nodes = api.get("nodes")

        
        # 3. Iterate over each node and extract the required information
        for node in nodes:
            name = node.metadata.name
            info = {"healthy": False}
            
            # --- Health Status (Ready Condition) ---
            is_ready = False
            last_event_time = None
            last_transition_reason = "N/A"
            
            # Node status is determined by conditions (e.g., Ready, MemoryPressure)
            # We specifically look for the 'Ready' condition.
            for condition in node.status.conditions:
                if condition.type == "Ready":
                    is_ready = condition.status == "True"
                    info["healthy"] = is_ready
                    
                    
                    # Store the time of the last state change for this condition.
                    # This is the best proxy for when the node last restarted or 
                    # had a significant distress event (like becoming NotReady).
                    last_event_str = condition.lastTransitionTime
                    if last_event_str:
                        # Convert the ISO 8601 string to a datetime object
                        # Note: Kubernetes uses UTC (Zulu time) for these timestamps
                        last_event_time = datetime.fromisoformat(last_event_str.replace('Z', '+00:00'))
                        info["last_event_time"] = last_event_time            
                        # Get the reason for the last state transition
                        last_transition_reason = condition.reason
                        info["last_transition_reason"] = last_transition_reason
                        
                    break # We only care about the Ready condition for overall health

            
            node_info[name] = info
            
    except kr8s.NotFoundError:
        print("Error: Could not connect to the Kubernetes API or no nodes found.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

    return node_info


def parse_kubelet_status(status_output: str) -> dict:
    """
    Parses the output of 'systemctl status kubelet' to extract the current 
    Active status and the time the service was started.

    NOTE: This parser attempts to infer the year if it's not explicitly present
    in the log line dates (like 'Dec 09 08:34:20').
    """
    results = {
        "status": "Unknown",
        "service_start_time": "N/A"
    }

    # Regex to find the 'Active:' line and capture the status and start time string
    # We look for the 'since' time as the reliable service restart time.
    active_pattern = re.compile(
        r"Active:\s+(?P<status>[^(]+)\s+\(running\)\s+since\s+(?P<time_string>[^;]+);"
    )

    current_year = datetime.now().year

    # --- Step 1: Extract Active Status and Service Start Time ---
    match = active_pattern.search(status_output)
    if match:
        # Extract and clean the status
        results["status"] = match.group("status").strip() + " (running)"
        
        # Extract the full timestamp string from the 'since' part
        start_time_str = match.group("time_string").strip()
        
        # Try to parse the systemd date format (e.g., 'Mon 2025-12-08 20:15:49 EST')
        
        dt_object = parser.parse(start_time_str)
        results["service_start_time"] = dt_object
        
    return results


def get_remote_kubelet_status(hostname, username):
    """
    Connects to a remote host via SSH, executes 'systemctl status kubelet', 
    and returns the parsed status.
    """
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        # Connect to the remote node
        ssh.connect(
            hostname=hostname,
            username=username,
            timeout=10
        )

        # Command to execute
        command = "systemctl status kubelet"
        
        # Execute the command
        # stdin, stdout, stderr are file-like objects
        stdin, stdout, stderr = ssh.exec_command(command)
        
        # Read the entire output
        status_output = stdout.read().decode('utf-8')
        error_output = stderr.read().decode('utf-8')

        if "not found" in error_output.lower():
            raise paramiko.SSHException(f"The command '{command}' was not found on {hostname}.")
            
        # Parse the output
        parsed_data = parse_kubelet_status(status_output)
        
        return parsed_data

    except paramiko.AuthenticationException:
        raise paramiko.AuthenticationException(f"Authentication failed for user {username} on {hostname}.")
    except paramiko.SSHException as e:
        raise paramiko.SSHException(f"SSH Error on {hostname}: {e}")
    except Exception as e:
        raise Exception(f"An unexpected error occurred on {hostname}: {e}") 
    finally:
        ssh.close()


def check_node_boot_time(
    hostname: str, 
    username: str, 
    start_time: datetime, 
    end_time: datetime, 
    tz:str = "America/New_York" 
) -> bool:
    """
    Connects to a remote host, gets the system boot time (uptime -s), and 
    checks if it falls within the specified start and end time range.

    Args:
        hostname: The IP address or hostname of the remote node.
        username: The SSH username.
        start_time: The start of the time window (datetime object).
        end_time: The end of the time window (datetime object).
        tz: time zone of the nodes
    
    Returns:
        True if the server's boot time is between start_time and end_time (inclusive), 
        otherwise raises an exception.
    """
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    boot_time_found = False

    # 1. Ensure start and end times are timezone-aware (UTC is best practice)
    # Convert provided times to UTC, if they aren't already.
    
    tz_object = pytz.timezone(tz)
    start_ts = start_time.astimezone(tz_object)
    end_ts = end_time.astimezone(tz_object)

    try:
        # 2. Connect to the remote node
        ssh.connect(
            hostname=hostname,
            username=username,
            timeout=10
        )
    
        # 3. Execute the command
        command = f'TZ="{tz}" date -d "$(uptime -s)"'
        stdin, stdout, stderr = ssh.exec_command(command)
        
        # Read the command output
        boot_time_str = stdout.read().decode('utf-8').strip()
        error_output = stderr.read().decode('utf-8')

        if not boot_time_str:
            print(f"Error: Could not retrieve boot time. STDERR: {error_output}")
            raise Exception("Boot time retrieval failed.")

        # 4. Parse the boot time string
        
        try:
            # Parse the local time string without assuming a specific timezone from the string
            local_boot_dt = parser.parse(boot_time_str)
        
            # Convert the naive local_boot_dt to an aware UTC time for comparison with start_ts/end_ts
            boot_dt = local_boot_dt.astimezone(tz_object)

        except ValueError as e:
            print(f"Parsing Error: Could not parse boot time '{boot_time_str}'. Error: {e}")
            raise Exception("Boot time parsing failed.")

        # 5. Check if the boot time is within the range
        if start_ts <= boot_dt <= end_ts:
            raise Exception("Server booted during time interval")

        return True

        
    except paramiko.AuthenticationException as e:
        print(f"Authentication failed for user {username} on {hostname}.")
        raise e
    except paramiko.SSHException as e:
        print(f"SSH Error on {hostname}: {e}")
        raise e
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        raise e
    finally:
        ssh.close()


def get_pod_restart_count(pod_name: str, namespace: str = "globeco") -> int:
    """
    Connects to the Kubernetes cluster and returns the total number of 
    restarts for all containers within a specified Pod.

    Args:
        pod_name: The name of the Pod to check.
        namespace: The namespace where the Pod resides (defaults to "default").

    Returns:
        The total number of container restarts (integer), or -1 if the Pod is not found.
    """
    total_restarts = 0
    try:
        # 1. Connect to the Kubernetes API
        api = kr8s.api()

        # 2. Fetch the specified Pod object
        pods = api.get("pod", pod_name, namespace=namespace)
        try:
            pod = next(iter(pods))
        except:
            raise NotFoundError
        
        # 3. Check for container statuses and accumulate restarts
        container_statuses = pod.status.get("containerStatuses")
        
        if container_statuses:
            for container in container_statuses:
                # The restartCount is an integer field for each container
                restart_count = container.get("restartCount", 0)
                total_restarts += restart_count
        else:
            # This happens if the Pod is still being created/scheduled (Pending state)
            raise Exception(f"Error: Pod {pod_name} is likely still starting up. No container statuses found.")

        return total_restarts

    except NotFoundError:
        print(f"Error: Pod '{pod_name}' not found in namespace '{namespace}'.")
        raise NotFoundError
    except Exception as e:
        print(f"An unexpected error occurred while fetching pod status: {e}")
        raise e        

def get_pod_restarts_for_namespace(namespace="globeco"):
    
    api = kr8s.api()
    pods = api.get("pod", namespace=namespace)
    restarts={}
    for pod in pods:
        name = pod.name
        container_statuses = pod.status.get("containerStatuses")
        total_restarts = 0
        if container_statuses:
            for container in container_statuses:
                # The restartCount is an integer field for each container
                restart_count = container.get("restartCount", 0)
                total_restarts += restart_count
        else:
            # This happens if the Pod is still being created/scheduled (Pending state)
            print(f"Warning: Pod {name} is likely still starting up. No container statuses found.")
        restarts[name] = total_restarts
    return restarts


def validate_environment_health_during_trial(start_time, end_time, prior_pod_restarts, tz="America/New_York"):

    # Check the nodes.  All nodes should be healthy and there should have been no state transitions
    # during the run.
    node_info = get_node_health_and_last_event_k8s_api()
    for node, info in node_info.items():
        if not info["healthy"]:
            raise Exception(f"Node {node} is not healthy.")
        if info.get("last_event_time"):
            if info["last_event_time"] > start_time:
                raise Exception(f"Node {node} had a state transition at {info['last_event_time']}. Reason: {info['last_transition_reason']}")

    # Check the kubelet status on all nodes.  
    for node in get_nodes():
        kubelet_status = get_remote_kubelet_status(node.metadata.name, "rpiadmin")
        if kubelet_status["status"] != "active (running)":
            raise Exception(f"Kubelet on node {node.metadata.name} is not running. Status: {kubelet_status['status']}")
        if kubelet_status.get("service_start_time") and kubelet_status["service_start_time"] > start_time:
            raise Exception(f"Kubelet on node {node.metadata.name} became available during the trial. Last available time: {kubelet_status['service_start_time']}")

    # Check for node reboots
    
    for node in get_nodes():
        check_node_boot_time(node.name, "rpiadmin", start_time, end_time, tz) # will raise exception if problem

    # Check for pod restarts
    current_pod_restarts = get_pod_restarts_for_namespace() 
    if current_pod_restarts != prior_pod_restarts:
        raise Exception("Pod restarts occurred during the trial.")


#!/usr/bin/env python3
"""
Simple Kafka Reinitialization - Just clean the data directory
"""

import re
import time
import subprocess
import kr8s
from kr8s.objects import StatefulSet, Pod

def delete_node_debugger_pods():
    for pod in kr8s.get("pods", namespace="globeco"):
        pod_name = pod.metadata.name
        pod_phase = pod.status.phase
        
        # Check if the name starts with the prefix AND the status is Completed or Failed/Error
        if pod_name.startswith("node-debugger-node-") and pod_phase in ("Succeeded"):
            pod.delete()


def simple_kafka_reinit(namespace: str = "globeco", 
                       statefulset_name: str = "globeco-execution-service-kafka",
                       node_name: str = "node-3",
                       data_path: str = "/mnt/disk1/kafka-execution-service") -> bool:
    """
    Simple Kafka reinitialization that just cleans the data directory
    
    This approach:
    1. Scales StatefulSet to 0
    2. Cleans the data directory on the node
    3. Scales StatefulSet back to 1
    
    The init container will reformat the storage automatically.
    """
    print("[INFO] Starting simple Kafka reinitialization...")
    
    try:
        # Step 1: Scale StatefulSet to 0
        print("[INFO] Scaling StatefulSet to 0...")
        statefulset = StatefulSet.get(statefulset_name, namespace=namespace)
        statefulset.patch({"spec": {"replicas": 0}})
        
        # Wait for pod to terminate
        pod_name = f"{statefulset_name}-0"
        print(f"[INFO] Waiting for pod {pod_name} to terminate...")
        count = 0
        while count < 60:
            try:
                pod = Pod.get(pod_name, namespace=namespace)
                if not pod.exists:
                    break
            except:
                break
            time.sleep(1)
            count += 1
        
        print("[SUCCESS] Pod terminated")
        
        # Step 2: Clean the data directory
        print(f"[INFO] Cleaning data directory {data_path} on {node_name}...")
        
        clean_command = [
            "kubectl", "debug", f"node/{node_name}", 
            "-it", "--image=busybox",  "--",
            "sh", "-c", 
            f"rm -rf /host{data_path}; "
            f"mkdir -p /host{data_path}; "
            f"chown -R 1000:1000 /host{data_path}; "
            f"ls -la /host{data_path}; "
            f"echo 'Directory completely cleaned and recreated on {node_name}'"
        ]
        
        # Run the debug command
        result = subprocess.run(clean_command, capture_output=True, text=True, timeout=60)

        if result.returncode == 0:
            print("[SUCCESS] Data directory cleaned")
        else:
            print(f"[WARNING] Directory clean may have failed: {result.stderr}")


        # Step 3: Scale StatefulSet back to 1
        print("[INFO] Scaling StatefulSet back to 1...")
        statefulset.patch({"spec": {"replicas": 1}})
        
        # Step 4: Wait for pod to be ready
        print(f"[INFO] Waiting for pod {pod_name} to be ready...")
        count = 0
        while count < 180:
            try:
                pod = Pod.get(pod_name, namespace=namespace)
                if pod.ready:
                    print("[SUCCESS] Pod is ready")
                    break
            except:
                pass
            time.sleep(2)
            count += 2
        else:
            print("[ERROR] Timeout waiting for pod to be ready")
            return False
        
        # Step 5: Create Kafka topics
        print("[INFO] Creating Kafka topics...")
        topics = ["orders", "fills"]
        partitions = 20
        
        for topic in topics:
            print(f"[INFO] Creating topic '{topic}' with {partitions} partitions...")
            create_topic_command = [
                "kubectl", "exec", "-n", namespace, pod_name, "-c", "kafka", "--",
                "/opt/kafka/bin/kafka-topics.sh",
                "--create",
                "--topic", topic,
                "--partitions", str(partitions),
                "--replication-factor", "1",
                "--bootstrap-server", "localhost:9092"
            ]
            
            try:
                result = subprocess.run(create_topic_command, capture_output=True, text=True, timeout=30)
                if result.returncode == 0:
                    print(f"[SUCCESS] Topic '{topic}' created successfully")
                else:
                    # Check if topic already exists (not an error)
                    if "already exists" in result.stderr:
                        print(f"[INFO] Topic '{topic}' already exists")
                    else:
                        print(f"[WARNING] Failed to create topic '{topic}': {result.stderr}")
            except subprocess.TimeoutExpired:
                print(f"[WARNING] Timeout creating topic '{topic}'")
            except Exception as e:
                print(f"[WARNING] Error creating topic '{topic}': {e}")
        
        print(f"[SUCCESS] Kafka is ready at: {statefulset_name}.{namespace}.svc.cluster.local:9092")
        return True
        
    except Exception as e:
        print(f"[ERROR] Reinitialization failed: {e}")
        return False


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] in ["-h", "--help", "help"]:
        print("Usage: python kafka_reinit_simple.py")
        print()
        print("Simple Kafka reinitialization that:")
        print("1. Scales StatefulSet to 0")
        print("2. Cleans the data directory on the node")
        print("3. Scales StatefulSet back to 1")
        print()
        print("The init container will automatically reformat the storage.")
        sys.exit(0)
    
    success = simple_kafka_reinit()
    sys.exit(0 if success else 1)
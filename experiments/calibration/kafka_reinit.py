#!/usr/bin/env python3
"""
Kafka Reinitialization Module for Microservice Benchmarks
This module quickly reinitializes Kafka to ensure each test starts from the same clean state
"""

import time
import subprocess
from typing import Optional
import kr8s
from kr8s.objects import StatefulSet, PersistentVolumeClaim, Pod


class KafkaReinitializer:
    """Handles Kafka reinitialization for benchmark testing"""
    
    def __init__(self, namespace: str = "globeco", 
                 statefulset_name: str = "globeco-execution-service-kafka",
                 pvc_name: str = "kafka-data-globeco-execution-service-kafka-0"):
        self.namespace = namespace
        self.statefulset_name = statefulset_name
        self.pvc_name = pvc_name
        self.pod_name = f"{statefulset_name}-0"
    
    def wait_for_resource_deletion(self, resource, timeout: int = 60) -> bool:
        """Wait for a Kubernetes resource to be deleted"""
        print(f"[INFO] Waiting for {resource.kind}/{resource.name} to be deleted...")
        
        count = 0
        while count < timeout:
            try:
                resource.refresh()
                if not resource.exists:
                    print(f"[SUCCESS] {resource.kind}/{resource.name} deleted")
                    return True
            except Exception:
                # Resource likely deleted
                print(f"[SUCCESS] {resource.kind}/{resource.name} deleted")
                return True
            
            time.sleep(1)
            count += 1
        
        print(f"[ERROR] Timeout waiting for {resource.kind}/{resource.name} deletion")
        return False
    
    def wait_for_pod_ready(self, timeout: int = 180) -> bool:
        """Wait for Kafka pod to be ready"""
        print(f"[INFO] Waiting for pod/{self.pod_name} to be ready...")
        
        count = 0
        while count < timeout:
            try:
                pod = Pod.get(self.pod_name, namespace=self.namespace)
                if pod.ready:
                    print(f"[SUCCESS] pod/{self.pod_name} is ready")
                    return True
            except Exception:
                # Pod might not exist yet
                pass
            
            time.sleep(2)
            count += 2
        
        print(f"[ERROR] Timeout waiting for pod/{self.pod_name} to be ready")
        return False
    
    def wait_for_pvc_bound(self, timeout: int = 60) -> bool:
        """Wait for PVC to be bound"""
        print(f"[INFO] Waiting for pvc/{self.pvc_name} to be bound...")
        
        count = 0
        while count < timeout:
            try:
                pvc = PersistentVolumeClaim.get(self.pvc_name, namespace=self.namespace)
                if pvc.status.phase == "Bound":
                    print(f"[SUCCESS] pvc/{self.pvc_name} is bound")
                    return True
            except Exception:
                # PVC might not exist yet
                pass
            
            time.sleep(1)
            count += 1
        
        print(f"[ERROR] Timeout waiting for pvc/{self.pvc_name} to be bound")
        return False
    
    def clean_node_directory(self, node_name: str = "node-3") -> bool:
        """Clean the Kafka data directory on the node using a privileged cleanup pod"""
        print(f"[INFO] Cleaning Kafka data directory on {node_name}...")
        
        cleanup_pod_yaml = f"""
apiVersion: v1
kind: Pod
metadata:
  name: kafka-cleanup-temp
  namespace: {self.namespace}
spec:
  restartPolicy: Never
  nodeSelector:
    kubernetes.io/hostname: {node_name}
  hostPID: true
  hostNetwork: true
  securityContext:
    runAsUser: 0
    runAsGroup: 0
    fsGroup: 0
  containers:
  - name: cleanup
    image: busybox
    securityContext:
      privileged: true
      runAsUser: 0
    command:
    - /bin/sh
    - -c
    - |
      echo "Cleaning Kafka data directory..."
      cd /mnt/disk1/kafka-execution-service
      rm -rf * .[!.]* 2>/dev/null || true
      echo "Directory cleaned"
      chown -R 1000:1000 /mnt/disk1/kafka-execution-service
      echo "Permissions set"
    volumeMounts:
    - name: kafka-data
      mountPath: /mnt/disk1/kafka-execution-service
  volumes:
  - name: kafka-data
    hostPath:
      path: /mnt/disk1/kafka-execution-service
      type: Directory
"""
        
        try:
            # Create cleanup pod
            with open('/tmp/kafka-cleanup.yaml', 'w') as f:
                f.write(cleanup_pod_yaml)
            
            result = subprocess.run(['kubectl', 'apply', '-f', '/tmp/kafka-cleanup.yaml'], 
                                  capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                print(f"[ERROR] Failed to create cleanup pod: {result.stderr}")
                return False
            
            # Wait for pod to complete
            print("[INFO] Waiting for cleanup to complete...")
            count = 0
            while count < 60:
                result = subprocess.run(['kubectl', 'get', 'pod', 'kafka-cleanup-temp', 
                                       '-n', self.namespace, '-o', 'jsonpath={.status.phase}'], 
                                      capture_output=True, text=True)
                if result.stdout.strip() == 'Succeeded':
                    print("[SUCCESS] Cleanup completed")
                    break
                elif result.stdout.strip() == 'Failed':
                    print("[ERROR] Cleanup pod failed")
                    return False
                time.sleep(1)
                count += 1
            
            # Clean up the cleanup pod
            subprocess.run(['kubectl', 'delete', 'pod', 'kafka-cleanup-temp', '-n', self.namespace], 
                          capture_output=True)
            
            return True
            
        except Exception as e:
            print(f"[ERROR] Failed to clean node directory: {e}")
            return False

    def reinitialize(self) -> bool:
        """
        Reinitialize Kafka by scaling StatefulSet to 0, cleaning data, deleting PVC/PV, and scaling back up
        
        Returns:
            bool: True if successful, False otherwise
        """
        print("[INFO] Starting Kafka reinitialization for benchmark testing...")
        
        try:
            # Step 1: Scale StatefulSet to 0 (safer than deleting)
            print("[INFO] Scaling StatefulSet to 0 to stop Kafka...")
            statefulset = StatefulSet.get(self.statefulset_name, namespace=self.namespace)
            statefulset.spec.replicas = 0
            statefulset.patch({"spec": {"replicas": 0}})
            
            # Wait for pod to be terminated
            try:
                pod = Pod.get(self.pod_name, namespace=self.namespace)
                self.wait_for_resource_deletion(pod, timeout=30)
            except Exception:
                # Pod might already be gone
                print("[INFO] Pod already terminated")
            
            # Step 2: Delete the PVC
            print("[INFO] Deleting PVC...")
            try:
                pvc = PersistentVolumeClaim.get(self.pvc_name, namespace=self.namespace)
                pvc.delete()
                self.wait_for_resource_deletion(pvc, timeout=30)
            except Exception as e:
                print(f"[WARNING] Could not delete PVC: {e}")
            
            # Step 3: Clean the actual data directory on the node
            if not self.clean_node_directory():
                print("[ERROR] Failed to clean node directory")
                return False
            
            # Step 4: Scale StatefulSet back to 1 (this will create new PVC and reinitialize)
            print("[INFO] Scaling StatefulSet back to 1 with fresh storage...")
            statefulset.patch({"spec": {"replicas": 1}})
            
            # Step 5: Wait for new PVC to be created and bound
            if not self.wait_for_pvc_bound(timeout=60):
                return False
            
            # Step 6: Wait for Kafka pod to be ready
            if not self.wait_for_pod_ready(timeout=180):
                return False
            
            print("[SUCCESS] Kafka reinitialization completed successfully!")
            
            # Show final status
            print("\n[INFO] Current status:")
            try:
                pod = Pod.get(self.pod_name, namespace=self.namespace)
                pvc = PersistentVolumeClaim.get(self.pvc_name, namespace=self.namespace)
                print(f"Pod: {pod.name} - Status: {pod.status.phase}")
                print(f"PVC: {pvc.name} - Status: {pvc.status.phase}")
            except Exception as e:
                print(f"[WARNING] Could not get status: {e}")
            
            print(f"\n[SUCCESS] Kafka is ready for benchmark testing at: {self.statefulset_name}.{self.namespace}.svc.cluster.local:9092")
            return True
            
        except Exception as e:
            print(f"[ERROR] Reinitialization failed: {e}")
            return False


# Convenience functions for direct usage
def reinitialize_kafka(namespace: str = "globeco", 
                      statefulset_name: str = "globeco-execution-service-kafka",
                      pvc_name: str = "kafka-data-globeco-execution-service-kafka-0") -> bool:
    """
    Convenience function to reinitialize Kafka
    
    Args:
        namespace: Kubernetes namespace
        statefulset_name: Name of the Kafka StatefulSet
        pvc_name: Name of the Kafka PVC
    
    Returns:
        bool: True if successful, False otherwise
    """
    reinitializer = KafkaReinitializer(namespace, statefulset_name, pvc_name)
    return reinitializer.reinitialize()


# CLI usage
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] in ["-h", "--help", "help"]:
        print("Usage: python kafka_reinit.py")
        print()
        print("This script reinitializes Kafka by:")
        print("1. Scaling the StatefulSet to 0 (stops Kafka)")
        print("2. Deleting the PVC (wipes all data)")
        print("3. Scaling the StatefulSet back to 1 (fresh start with new storage)")
        print()
        print("This ensures each benchmark test starts with a completely clean Kafka instance.")
        sys.exit(0)
    
    success = reinitialize_kafka()
    sys.exit(0 if success else 1)
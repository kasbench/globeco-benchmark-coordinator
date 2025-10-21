#!/usr/bin/env python3
"""
Simple Python program that collects cpu temperatures and pushes them to 
Prometheus Pushgateway via kr8s NodePort discovery.
"""

import time
import random
import requests
import json
from datetime import datetime

import paramiko
import pandas as pd
import kr8s
from kr8s import Api
from kr8s.objects import Service


COMMAND = "sensors -j"

def get_ssh_client(node_name, username="rpiadmin", timeout=5):

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        client.connect(hostname=node_name, username=username, timeout=timeout)
    except paramiko.AuthenticationException:
        print("Authentication failed.")
    except paramiko.SSHException as e:
        print(f"SSH error: {e}")
    except Exception as e:
        print(f"An error occurred: {e}")

    return client


def get_thermals(client, command, timeout=5):
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout)

    output = stdout.read().decode('utf-8')
    errors = stderr.read().decode('utf-8')

    if errors:
        raise Exception(f"Error executing command: {errors}")

    return json.loads(output)
        
def preprocess_thermals(thermal, cpu, node):
    if cpu == 'amd':
        return [node,
                cpu,
                {
                    "k10temp-pci-00c3": thermal["k10temp-pci-00c3"]["Tctl"]["temp1_input"],
                    "amdgpu-pci-0400": thermal["amdgpu-pci-0400"]["edge"]["temp1_input"],
                    "acpitz-acpi-0": thermal["acpitz-acpi-0"]["temp1"]["temp1_input"],
                    "nvme-pci-0100": thermal["nvme-pci-0100"]["Composite"]["temp1_input"]
                }]
    if cpu == 'rpi':
        return [node,
                cpu,
                {
                    "cpu_thermal-virtual-0": thermal["cpu_thermal-virtual-0"]["temp1"]["temp1_input"],
                    "rp1_adc-isa-0000": thermal["rp1_adc-isa-0000"]["temp1"]["temp1_input"],
                    "nvme-pci-10100": thermal["nvme-pci-10100"]["Composite"]["temp1_input"] 
                }]
        

NODES = (('server', 4, 'rpi'),
         ('node-0', 4, 'rpi'),
         ('node-1', 4, 'rpi'),
         ('node-2', 4, 'rpi'),
         ('node-3', 16, 'amd'),
         ('node-4', 16, 'amd'),
         ('node-5', 16, 'amd'),
        )

NODE_CPU = {node: cpu for node, _, cpu in NODES}

METRICS = {
    "k10temp-pci-00c3": "AMD CPU Temperature",
    "amdgpu-pci-0400": "AMD GPU Temperature",
    "acpitz-acpi-0": "Ambiant Temperature",
    "nvme-pci-0100": "NVMe Temperature",
    "cpu_thermal-virtual-0": "RPI CPU Temperature",
    "rp1_adc-isa-0000": "RPI ADC Temperature",
    "nvme-pci-10100": "NVMe Temperature"
}

def get_all_thermals_for_nodes(nodes, command, timeout=5):    
    thermal_record = []
    exceptions = []
    for _ in range(3):       # Retry up to 3 times
        try:
            for node, _, cpu in nodes:
                client = get_ssh_client(node, timeout=timeout)
                raw_thermals = get_thermals(client,command=command, timeout=timeout)
                if processed_thermals := preprocess_thermals(raw_thermals, cpu, node): 
                    thermal_record.append(processed_thermals)
                client.close()
            # print(f"Thermal record: {thermal_record}")
            return thermal_record
        except Exception as ex:
            exceptions.append(ex)
            
    raise Exception(f"Failed to get thermals after 3 attempts: {exceptions}")

def get_thermals_for_request(request, command="sensors -j", timeout=5):
    """
    Collects temperatures based on a request dictionary.  The request dictionary is in the form:
        {"node-1": [metric1, metric2],
         "node-2": [metric1, metric3], 
         ...}
    """
    thermal_record = []
    exceptions = []
    for _ in range(3):       # Retry up to 3 times
        try:
            for node, metrics in request.items():
                client = get_ssh_client(node, timeout=timeout)
                raw_thermals = get_thermals(client, command=command, timeout=timeout)
                if processed_thermals := preprocess_thermals(raw_thermals, NODE_CPU[node], node):
                    thermal_record.append(processed_thermals)
                client.close()
            # print(f"Thermal record: {thermal_record}")
            return thermal_record
        except Exception as ex:
            exceptions.append(ex)
            time.sleep(10)

    raise Exception(f"Failed to get thermals after 3 attempts: {exceptions}")


class MetricPusher:
    def __init__(self, namespace="monitor", service_name="pushgateway", job_name="globeco-thermals"):
        """
        Initialize the metric pusher.
        
        Args:
            namespace: Kubernetes namespace where Pushgateway is deployed
            service_name: Name of the Pushgateway service
            job_name: Job name for grouping metrics in Prometheus
        """
        self.namespace = namespace
        self.service_name = service_name
        self.job_name = job_name
        self.pushgateway_url = None
        
    def discover_pushgateway_nodeport(self):
        """
        Use kr8s to discover the Pushgateway NodePort endpoint.
        
        Returns:
            str: URL of the Pushgateway endpoint
        """
        try:
            # Create kr8s API client
            api = kr8s.api()
            
            # Get the Pushgateway service
            svc = Service.get(self.service_name, namespace=self.namespace, api=api)
            
            # Get NodePort details
            node_port = None
            for port in svc.spec.ports:
                if port.get('nodePort'):
                    node_port = port['nodePort']
                    break
            
            if not node_port:
                raise ValueError(f"No NodePort found for service {self.service_name}")
            
            # Get a node's external IP or internal IP
            nodes = api.get("nodes")
            node_ip = None
            
            for node in nodes:
                # Try to get external IP first
                for addr in node.status.addresses:
                    if addr['type'] == 'ExternalIP':
                        node_ip = addr['address']
                        break
                
                # Fall back to internal IP if no external IP
                if not node_ip:
                    for addr in node.status.addresses:
                        if addr['type'] == 'InternalIP':
                            node_ip = addr['address']
                            break
                
                if node_ip:
                    break
            
            if not node_ip:
                raise ValueError("Could not find any node IP address")
            
            pushgateway_url = f"http://{node_ip}:{node_port}"
            print(f"✓ Discovered Pushgateway at: {pushgateway_url}")
            return pushgateway_url
            
        except Exception as e:
            print(f"✗ Error discovering Pushgateway: {e}")
            raise
    
    def collect_metric(self):
        """
        Collect your custom metric. Replace this with your actual metric collection logic.
        
        Returns:
            float: The metric value
        """

        metric_values = get_all_thermals_for_nodes(NODES, COMMAND, timeout=5)

        return metric_values
    
    def push_metric(self, metric_name, metric_value, labels=None, metric_help="Custom metric", 
        grouping_keys=None):
        """
        Push a metric to Prometheus Pushgateway.
        
        Args:
            metric_name: Name of the metric (e.g., 'my_custom_metric')
            metric_value: Value of the metric
            metric_help: Help text describing the metric
        """
        if not self.pushgateway_url:
            self.pushgateway_url = self.discover_pushgateway_nodeport()
        
        # Use grouping keys if provided, otherwise use labels to create grouping keys
        # This ensures each unique combination gets its own slot in Pushgateway
        if grouping_keys is None and labels:
            grouping_keys = labels

        # Construct the URL for pushing metrics
        url = f"{self.pushgateway_url}/metrics/job/{self.job_name}"

        # Add grouping keys to the URL to distinguish between different metric groups
        if grouping_keys:
            for key, value in grouping_keys.items():
                # URL-encode the values to handle special characters
                from urllib.parse import quote
                url += f"/{key}/{quote(str(value))}"

        # Format labels for the metric
        label_str = ""
        if labels:
            label_pairs = [f'{key}="{value}"' for key, value in labels.items()]
            label_str = "{" + ",".join(label_pairs) + "}"
        
        # Format metric in Prometheus text format
        metric_data = f"""# HELP {metric_name} {metric_help}
# TYPE {metric_name} gauge
{metric_name}{label_str} {metric_value}
"""
        
        try:
            # print(f"Pushing metric: {metric_name}={metric_value} with data: {metric_data}.  URL={url}")
            response = requests.post(url, data=metric_data)
            response.raise_for_status()
            labels_display = f" {labels}" if labels else ""
            print(f"✓ Pushed metric: {metric_name}{labels_display}={metric_value}")
            return True
        except requests.exceptions.RequestException as e:
            print(f"✗ Error pushing metric: {e}.  Response={response.text}")
            return False
    
    def run(self, interval=15):
        """
        Continuously collect and push metrics at the specified interval.
        
        Args:
            interval: Time in seconds between metric pushes
        """
        print(f"Starting metric pusher (interval: {interval}s)")
        print(f"Job: {self.job_name}")
        print(f"Looking for Pushgateway service: {self.service_name} in namespace: {self.namespace}\n")
        
        # Discover the Pushgateway endpoint once at startup
        self.pushgateway_url = self.discover_pushgateway_nodeport()
        
        while True:
            try:
                # Collect your metric
                metric_values = self.collect_metric()
                
                # Push to Prometheus
                for node, cpu, metrics in metric_values:

                    labels = {
                        "node": node,      # Replace with actual node identifier
                        "processor": cpu   # Replace with actual processor identifier
                    }

                    for key, value in metrics.items():
                        self.push_metric(
                            metric_name=key.replace('-', '_'),
                            metric_value=value,
                            labels=labels,
                            metric_help=METRICS[key]
                        )
                        
                
                # Wait before next push
                time.sleep(interval)
                
            except KeyboardInterrupt:
                print("\n✓ Shutting down gracefully...")
                break
            except Exception as e:
                print(f"✗ Error in main loop: {e}")
                time.sleep(interval)


def main():
    pusher = MetricPusher(
        namespace="monitor",                 # Namespace where Pushgateway is deployed
        service_name="pushgateway",          # Name of the Pushgateway service
        job_name="globeco-thermals"          # Job name for grouping your metrics
    )
    
    # Run the pusher (pushes metric every 15 seconds)
    pusher.run(interval=15)


if __name__ == "__main__":
    main()
#!/usr/bin/env python3

import sys
from common import scale_microservice_deployments, minio_client
from ssh import set_cpu_governor_to_performance
from horizontal_scaling_experiment import initialize_only


def main():
    if len(sys.argv) < 2:
        print("Usage: python script.py <command> [parameter]")
        return
    
    command = sys.argv[1]
    
    if command == "help":
        print("Usage: python script.py <command> [parameter]")
        print("")
        print("Commands:")
        print("  set_replicas <number>                               Set the number of replicas for microservice deployments")
        print("  set_governor <governor>                             Set CPU governor (performance or other)")
        print("  initialize                                          Initialize the environment for experiments")
        print(". minio_copy <bucket> <minio_file_name> <local_file>. Copies a file to MinIO")
        print("  help                     Show this help message")
    elif command == "set_replicas":
        if len(sys.argv) < 3:
            print("Usage: python script.py set_replicas <number>")
            return
        try:
            replicas = int(sys.argv[2])
            scale_microservice_deployments(replicas)
            print(f"Set replicas to {replicas}")
        except ValueError:
            print("Error: Number of replicas must be an integer")
        except Exception as e:
            print(f"Error: {e}")
    elif command == "set_governor":
        if len(sys.argv) < 3:
            print("Usage: python script.py set_governor <governor>")
            return
        try:
            governor = sys.argv[2]
            if governor == "performance":
                set_cpu_governor_to_performance(revert=False)
            else:
                set_cpu_governor_to_performance(revert=True)
            print(f"Set governor to {governor}")
        except Exception as e:
            print(f"Error: {e}")
    elif command == "initialize":
        try:
            initialize_only()
            print("Environment initialized successfully")
        except Exception as e:
            print(f"Error: {e}")
    elif command == "minio_copy":
        if len(sys.argv) < 5:
            print("Usage: python script.py minio_copy <bucket> <minio_file_name> <local_file>")
            return
        try:
            bucket = sys.argv[2]
            minio_filename = sys.argv[3]
            local_filename = sys.argv[4]
            minio_client.fput_object(bucket, minio_filename, local_filename)
            print(f"Copied {local_filename} to {bucket}/{minio_filename}")
        except Exception as e:
            print(f"Error: {e}")    
    else:
        print(f"Unknown command: {command}")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Command-line interface for running Experiment 1.
"""
import argparse
from calibration_experiment import run_experiment_1


def main():
    parser = argparse.ArgumentParser(
        description="Run Experiment 1 calibration tests"
    )
    
    parser.add_argument(
        "--bucket-name-prefix",
        type=str,
        default="experiment-1",
        help="Prefix for MinIO bucket names (default: experiment-1)"
    )
    
    parser.add_argument(
        "--microservices",
        type=str,
        nargs="+",
        default=None,
        help="List of microservices to test (default: all microservices)"
    )
    
    parser.add_argument(
        "--replicas",
        type=int,
        default=1,
        help="Number of replicas for each microservice (default: 1)"
    )
    
    parser.add_argument(
        "--trial-numbers",
        type=int,
        nargs="+",
        default=None,
        help="List of trial numbers to run (default: 0-199)"
    )
    
    parser.add_argument(
        "--trial-length",
        type=str,
        default="10m",
        help="Length of each trial (default: 10m)"
    )
    
    parser.add_argument(
        "--trial-users",
        type=str,
        nargs="+",
        default=None,
        help="List of user counts to test (default: ['50'])"
    )
    
    args = parser.parse_args()
    
    run_experiment_1(
        bucket_name_prefix=args.bucket_name_prefix,
        microservices=args.microservices,
        replicas=args.replicas,
        trial_numbers=args.trial_numbers,
        trial_length=args.trial_length,
        trial_users=args.trial_users
    )


if __name__ == "__main__":
    main()

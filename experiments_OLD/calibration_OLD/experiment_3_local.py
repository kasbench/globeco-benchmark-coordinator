#!/usr/bin/env python3
"""
Command-line interface for running local calibration experiments.
"""
import argparse
from experiments.calibration.runner import run


def main():
    parser = argparse.ArgumentParser(
        description="Run local calibration experiments"
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
        "--verbose",
        action="store_true",
        help="Enable verbose output (default: False)"
    )
    
    parser.add_argument(
        "--wait-for-cooling",
        action="store_true",
        help="Wait for system cooling before running trials (default: False)"
    )
    
    args = parser.parse_args()

    print("Starting local calibration experiment with the following parameters:")
    print(f"Bucket Name Prefix: {args.bucket_name_prefix}")
    print(f"Trial Numbers: {args.trial_numbers}")
    print(f"Users: {args.users}")
    print(f"Resource Profile: {args.resource_profile}")
    print(f"Trial Lengths (minutes): {args.trial_lengths_minutes}")
    print(f"Microservices: {args.microservices}")
    print(f"Replicas: {args.replicas}")
    print(f"Validate: {not args.no_validate}")
    print(f"Verbose: {args.verbose}")
    print(f"Wait for Cooling: {args.wait_for_cooling}")
    
    run(
        bucket_name_prefix=args.bucket_name_prefix,
        trial_numbers=args.trial_numbers,
        users=args.users,
        resource_profile=args.resource_profile,
        trial_lengths_minutes=args.trial_lengths_minutes,
        microservices=args.microservices,
        replicas=args.replicas,
        validate=not args.no_validate,
        verbose=args.verbose,
        overrides=None,
        wait_for_cooling_before_run=args.wait_for_cooling
    )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Command-line interface for running local calibration experiments.
"""
import argparse
from runner import run


def main():
    parser = argparse.ArgumentParser(
        description="Run local calibration experiments"
    )

    parser.add_argument(
        "--host",
        type=str,
        required=True,
        default="http://globeco-portfolio-management-portal:3000",
        help="Host name and port"
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
        "--skip-initialization",
        action="store_true",
        help="Skip initialization (restarts and database truncation) (default: False)"
    )
    
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose output (default: False)"
    )
    
    parser.add_argument(
        "--collect-thermal-metrics",
        action="store_true",
        help="Collect thermal metrics (default: False)"
    )
    
    parser.add_argument(
        "--wait-for-cooling",
        action="store_true",
        help="Wait for system cooling before running trials (default: False)"
    )
    
    args = parser.parse_args()

    microservices = args.microservices
    if microservices is None:
        microservices = ['globeco-allocation-service', 'globeco-confirmation-service', 
                 'globeco-execution-service', 
                 'globeco-fix-engine', 'globeco-order-service', 
                 'globeco-portfolio-accounting-service', 'globeco-portfolio-management-portal', 
                 'globeco-portfolio-service', 'globeco-pricing-service', 'globeco-security-service',
                 'globeco-trade-service', 'globeco-order-generation-service']

    print("Starting local calibration experiment with the following parameters:")
    print(f"Host: {args.host}")
    print(f"Bucket Name Prefix: {args.bucket_name_prefix}")
    print(f"Trial Numbers: {args.trial_numbers}")
    print(f"Users: {args.users}")
    print(f"Resource Profile: {args.resource_profile}")
    print(f"Trial Lengths (minutes): {args.trial_lengths_minutes}")
    print(f"Microservices: {microservices}")
    print(f"Replicas: {args.replicas}")
    print(f"Validate: {not args.no_validate}")
    print(f"Skip Initialization: {args.skip_initialization}")
    print(f"Verbose: {args.verbose}")
    print(f"Wait for Cooling: {args.wait_for_cooling}")
    print(f"Collect Thermal Metrics: {args.collect_thermal_metrics}")
    
    run(
        host=args.host,
        bucket_name_prefix=args.bucket_name_prefix,
        trial_numbers=args.trial_numbers,
        users=args.users,
        resource_profile=args.resource_profile,
        trial_lengths_minutes=args.trial_lengths_minutes,
        microservices=microservices,
        replicas=args.replicas,
        validate=not args.no_validate,
        verbose=args.verbose,
        overrides=None,
        wait_for_cooling_before_run=args.wait_for_cooling,
        skip_initialization=args.skip_initialization,
        collect_thermal_metrics=args.collect_thermal_metrics
    )


if __name__ == "__main__":
    main()

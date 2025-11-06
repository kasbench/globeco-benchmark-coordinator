from typing import Any

from experiments.calibration import common



def get_kubernetes_resources(version_name: str) -> list[dict[str, dict[str, str]] | Any] | None:
    if version_name == "baseline":
        return [
            {'globeco-allocation-service': {'cpu_request': '200m', 'cpu_limit': '200m',
                                            'memory_request': '100Mi', 'memory_limit': '100Mi'}},
            {'globeco-confirmation-service': {'cpu_request': '200m', 'cpu_limit': '200m',
                                              'memory_request': '100Mi', 'memory_limit': '100Mi'}},
            {'globeco-execution-service': {'cpu_request': '600m', 'cpu_limit': '600m',
                                           'memory_request': '900Mi', 'memory_limit': '900Mi'}},
            {'globeco-fix-engine': {'cpu_request': '200m', 'cpu_limit': '200m',
                                    'memory_request': '100Mi', 'memory_limit': '100Mi'}},
            {'globeco-order-generation-service': {'cpu_request': '1', 'cpu_limit': '1',
                                       'memory_request': '700Mi', 'memory_limit': '700Mi'}},
            {'globeco-order-service': {'cpu_request': '1', 'cpu_limit': '1',
                                       'memory_request': '1100Mi', 'memory_limit': '1100Mi'}},
            {'globeco-portfolio-accounting-service': {'cpu_request': '200m', 'cpu_limit': '200m',
                                                      'memory_request': '100Mi', 'memory_limit': '100Mi'}},
            {'globeco-portfolio-management-portal': {'cpu_request': '600m', 'cpu_limit': '600m',
                                                      'memory_request': '200Mi', 'memory_limit': '200Mi'}},
            {'globeco-portfolio-service': {'cpu_request': '300m', 'cpu_limit': '300m',
                                           'memory_request': '200Mi', 'memory_limit': '200Mi'}},
            {'globeco-pricing-service': {'cpu_request': '1', 'cpu_limit': '1',
                                         'memory_request': '1000Mi', 'memory_limit': '1000Mi'}},
            {'globeco-security-service': {'cpu_request': '300m', 'cpu_limit': '300m',
                                           'memory_request': '200Mi', 'memory_limit': '200Mi'}},
            {'globeco-trade-service': {'cpu_request': '1', 'cpu_limit': '1',
                                       'memory_request': '1000Mi', 'memory_limit': '1000Mi'}}
        ]

    raise ValueError(f"Unknown version: {version_name}")



def get_trials(replicas:list[int], times:list[str], users:list[int], iterations:int):
    trials = []
    for replica in replicas:
        for time in times:
            for user in users:
                for iteration in range(iterations):
                    trials.append({'replica': replica, 'time': time, 'user': user, 'iteration': iteration})

    return trials



def run(replicas:list[int]=None, kubernetes_resources:str= "baseline", times:list[str]=None, users:list[int]=None,
        iterations:int=30, minio_prefix=None, validate=True, wait_for_cooling=True) -> int:

    # Process arguments
    if replicas is None:
        replicas = [1, 2, 4, 8, 16]
    if users is None:
        users = [75]
    if times is None:
        times = ["10m"]
    if minio_prefix is None:
        raise ValueError("minio_prefix cannot be None")


    minio_client = common.minio_client()
    kubernetes_resources = get_kubernetes_resources(kubernetes_resources)

    trials = get_trials(replicas, times, users, iterations)



    return 0




if __name__ == "__main__":
    run()
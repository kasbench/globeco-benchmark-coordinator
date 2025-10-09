from prometheus_api_client import PrometheusConnect, MetricRangeDataFrame
from kr8s.objects import Deployment
import pandas as pd

# Connect to your Prometheus server

def get_prometheus_connection(url="http://prometheus:31565", disable_ssl=True):
    prom = PrometheusConnect(
        url=url,  
        disable_ssl=disable_ssl            # set False if using HTTPS with valid cert
    )
    return prom


def get_prometheus_data(prom, microservices, metric_name, start_time, end_time, calculate_rate=True, namespace="globeco", range="1m", steps="10s", verbose=False ):
    df = None
    pods = []
    for microservice in microservices:
        deployment = Deployment.get(microservice, namespace=namespace)
        pod = deployment.pods()[0]
            
        if calculate_rate:
            query = f'rate({metric_name}{{pod="{pod.name}", image!=""}}[{range}])'
        else:
            query = f'{metric_name}{{pod="{pod.name}", image!=""}}'
        if verbose:
            print(query) 
        
        data = prom.custom_query_range(
            query=query,
            start_time=start_time,
            end_time=end_time,
            step=steps
        )
        
        temp_df = MetricRangeDataFrame(data)
        temp_df['pod'] = microservice
        if df is None:
            df = temp_df
        else:
            df = pd.concat([df, temp_df], axis = 0)

    return df






if __name__ == "__main__": 

    prom = get_prometheus_connection()

    # Check connection
    print(prom.check_prometheus_connection())


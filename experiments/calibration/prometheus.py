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
    if verbose:
        print(f"Getting Prometheus data for {metric_name} from {start_time} to {end_time}")
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
        if verbose:
            print(f"Retrieved {len(data)} data points for {microservice} ({pod.name})")
        temp_df = MetricRangeDataFrame(data)
        temp_df['pod'] = microservice
        if df is None:
            df = temp_df
        else:
            df = pd.concat([df, temp_df], axis = 0)
    print("Returning dataframe with shape:", df.shape)    
    return df


def get_prometheus_node_data(prom, node, metric_name, start_time, end_time,  namespace="monitor", steps="15s", verbose=False ):
    
    query = f'{metric_name}{{node="{node}"}}'
    if verbose:
        print(query) 
    
    data = prom.custom_query_range(
        query=query,
        start_time=start_time,
        end_time=end_time,
        step=steps
    )
    
    df = MetricRangeDataFrame(data)
    
    return df






if __name__ == "__main__": 

    prom = get_prometheus_connection()

    # Check connection
    print(prom.check_prometheus_connection())


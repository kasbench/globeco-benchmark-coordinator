import requests
import json
import random

base = "http://globeco.local:31510"

## Utility Functions

def pprint(obj:requests.Response):
    print(f"Status Code: {obj.status_code}")
    print(f"Reason: {obj.reason}")
    try:
        print(json.dumps(obj.json(), indent=4))
    except:
        print(f"Text: {obj.text}")


def random_integer(min:int=0, max:int=1_000_000_000_000 ) -> int:
    return random.randint(min, max)


# Portfolio Functions

def get_portfolios(base:str) -> requests.Response:
    portfolios = f"{base}/api/portfolios"
    response = requests.get(portfolios)
    return response


def post_portfolios(base:str, data:json) -> requests.Response:
    portfolios = f"{base}/api/portfolios"
    response = requests.post(portfolios, json=data)
    return response


def get_portfolio(base:str, id:str) -> requests.Response:
    portfolios = f"{base}/api/portfolios/{id}"
    response = requests.get(portfolios)
    return response


def put_portfolios(base:str, id:str, data:json) -> requests.Response:
    portfolios = f"{base}/api/portfolios/{id}"
    response = requests.put(portfolios, json=data)
    return response


def delete_portfolios(base:str, id:str, version:int) -> requests.Response:
    portfolios = f"{base}/api/portfolios/{id}?version={version}"
    response = requests.delete(portfolios)
    return response


# Investment Model Functions

def get_investment_models(base:str) -> requests.Response:
    models = f"{base}/api/models"
    response = requests.get(models)
    return response


def post_investment_models(base:str, data:json) -> requests.Response:
    models = f"{base}/api/models"
    response = requests.post(models, json=data)
    return response 


def get_investment_model(base:str, id:str) -> requests.Response:
    model = f"{base}/api/models/{id}"
    response = requests.get(model)
    return response 


def put_investment_model(base:str, id:str, data:json) -> requests.Response:
    model = f"{base}/api/models/{id}"
    response = requests.put(model, json=data)
    return response  


def delete_investment_model(base:str, id:str, version:int) -> requests.Response:
    model = f"{base}/api/models/{id}?version={version}"
    response = requests.delete(model)
    return response 


# Order Functions

def get_orders(base:str, offset:int=0, limit:int=100, status:str="", portfolio_id:str="") -> requests.Response:
    orders = f"{base}/api/orders?offset={offset}&limit={limit}"
    if status:
        orders += f"&status={status}"
    if portfolio_id:
        orders += f"&portfolio_id={portfolio_id}"
    response = requests.get(orders)
    return response


def get_order(base:str, id:str) -> requests.Response:
    order = f"{base}/api/orders/{id}"
    response = requests.get(order)
    return response


def post_orders(base:str, data:json) -> requests.Response:
    orders = f"{base}/api/orders"
    response = requests.post(orders, json=data)
    return response


def put_orders(base:str, id:str, data:json) -> requests.Response:
    orders = f"{base}/api/orders/{id}"
    response = requests.put(orders, json=data)
    return response


def delete_orders(base:str, id:str, version:int) -> requests.Response:
    orders = f"{base}/api/orders/{id}?version={version}"
    response = requests.delete(orders)
    return response


def submit_order(base:str, data:json) -> requests.Response:
    orders = f"{base}/api/orders/batch/submit"
    response = requests.post(orders, json=data)
    return response


# Trade Functions

def get_trades(base:str, offset:int=0, limit:int=100, status:str=None, blotter_id:str=None) -> requests.Response:
    trades = f"{base}/api/trades?offset={offset}&limit={limit}"
    if status:
        trades += f"&status={status}"
    if blotter_id:
        trades += f"&blotter_id={blotter_id}"
    response = requests.get(trades)
    return response


def get_trade(base:str, id:str) -> requests.Response:
    trade = f"{base}/api/trades/{id}"
    response = requests.get(trade)
    return response


def post_trades(base:str, data:json) -> requests.Response:
    trades = f"{base}/api/trades"
    response = requests.post(trades, json=data)
    return response


def delete_trades(base:str, id:str, version:int) -> requests.Response:
    trades = f"{base}/api/trades/{id}?version={version}"
    response = requests.delete(trades)
    return response


def put_trades(base:str, id:str, data:json) -> requests.Response:
    trades = f"{base}/api/trades/{id}"
    response = requests.put(trades, json=data)
    return response


def submit_trade(base:str, id:str) -> requests.Response:
    trades = f"{base}/api/trade-orders/{id}/submit"
    response = requests.post(trades)
    return response


def submit_trades(base:str, data:json) -> requests.Response:
    trades = f"{base}/api/trade-orders/batch/submit"
    response = requests.post(trades, json=data)
    return response

# Execution Functions

def get_executions(base:str, offset:int=0, limit:int=100, status:str=None, portfolio_id:str=None, start_date:str=None, end_date:str=None) -> requests.Response:
    executions = f"{base}/api/executions?offset={offset}&limit={limit}"
    if status:
        executions += f"&status={status}"
    if portfolio_id:
        executions += f"&portfolio_id={portfolio_id}"
    if start_date:
        executions += f"&start_date={start_date}"
    if end_date:
        executions += f"&end_date={end_date}"
    response = requests.get(executions)
    return response


def get_execution(base:str, id:str) -> requests.Response:
    execution = f"{base}/api/executions/{id}"
    response = requests.get(execution)
    return response


# Health Functions  

def get_health(base:str) -> requests.Response:
    health = f"{base}/api/health"
    response = requests.get(health)
    return response



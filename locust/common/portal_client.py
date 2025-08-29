from locust import HttpUser
import requests
import json
import random
import common.portal_client as portal_client


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

def get_portfolios(client:HttpUser) -> requests.Response:
    portfolios = f"/api/portfolios"
    response = client.get(portfolios, name="/api/portfolios")
    return response


# def post_portfolios(base:str, data:json) -> requests.Response:
#     portfolios = f"{base}/api/portfolios"
#     response = requests.post(portfolios, json=data)
#     return response


def get_portfolio(base:str, id:str) -> requests.Response:
    portfolios = f"{base}/api/portfolios/{id}"
    response = requests.get(portfolios)
    return response


def put_portfolios(base:str, id:str, data:json) -> requests.Response:
    portfolios = f"{base}/api/portfolios/{id}"
    response = requests.put(portfolios, json=data)
    return response


# def delete_portfolios(base:str, id:str, version:int) -> requests.Response:
#     portfolios = f"{base}/api/portfolios/{id}?version={version}"
#     response = requests.delete(portfolios)
#     return response


def post_portfolios(client:HttpUser, data:dict) -> requests.Response:
    portfolios = f"/api/portfolios"
    response = client.post(portfolios, json.dumps(data), name="/api/portfolios")
    return response

def delete_portfolios(client:HttpUser, id:str, version:int) -> requests.Response:
    portfolios = f"/api/portfolios/{id}?version={version}"
    response = client.delete(portfolios, name="/api/portfolios")
    return response


# Security Functions

# def get_securities(base:str) -> requests.Response:
#     securities = f"{base}/api/v1/securities"
#     response = requests.get(securities)
#     return response

def get_securities(client:HttpUser) -> requests.Response:
    securities = f"/api/securities"
    response = client.get(securities)
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

def rebalance_investment_model(client:HttpUser, id:str) -> requests.Response:
    model = f"/api/models/{id}/rebalance"
    # print(f"Rebalancing model: {model}")
    response = client.post(model, name="/api/models/{id}/rebalance")
    # print(f"Response: {response.json()}")
    return response

def get_rebalance(client:HttpUser, id:str) -> requests.Response:
    rebalance = f"/api/rebalances/{id}"
    response = client.get(rebalance, name="/api/rebalances/{id}")
    return response

def submit_rebalance(client:HttpUser, id:str) -> requests.Response:
    print(f"Submitting rebalance: {id}")
    rebalance = get_rebalance(client, id)
    if rebalance.ok:
        print(f"Number of portfolios rebalanced: {len(rebalance.json()['portfolios'])}")
        for portfolio in rebalance.json()['portfolios']:
            # print(f"Submitting rebalance for portfolio: {portfolio['portfolio_id']}")
            rebalance_path = "/api/rebalances/submit-positions"
            positions = portfolio['positions']
            positions = [{'security_id': position['security_id'], 'transaction_type': position['transaction_type'], 'trade_quantity': position['trade_quantity'], 'target_weight': position['target']} for position in positions]
            # print(f"Positions: {positions}")
            response = client.post(rebalance_path, json={'portfolioId': portfolio['portfolio_id'], 'positions': positions})
            if response.ok:
                # print(f"Submitted rebalance: {portfolio['portfolio_id']}")
                print(f"Response from submit-positions: {response.json()}")
                return response
            else:
                raise Exception(f"Failed to submit rebalance: {portfolio['portfolio_id']}.  Status code: {response.status_code}, Reason: {response.reason}  ")
    else:
        raise Exception(f"Failed to get rebalance: {id}.  Status code: {rebalance.status_code}, Reason: {rebalance.reason}  ")





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


def submit_order(client:HttpUser, data:json) -> requests.Response:
    orders = "/api/orders/batch/submit"
    response = client.post(orders, json=data)
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

def get_trade_by_order_id(client:HttpUser, id:str) -> requests.Response:
    trade = f"/api/trades?orderId={id}"
    response = client.get(trade, name="/api/trades?orderId")
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


def submit_trade(client:HttpUser, id:str, quantity:float) -> requests.Response:
    trades = f"/api/trade-orders/{id}/submit"
    data = {"destinationId": 1, "quantity": quantity}
    response = client.post(trades, json=data, name="/api/trade-orders/{id}/submit")
    return response


# curl -v -X POST -d '{"destinationId": 1, "quantity": 134}' "http://globeco.local:32080/api/trade-orders/50/submit"
    # Response:
    """
    {
        "id":37,
        "executionTimestamp":"2025-08-11T12:31:26.645610472Z",
        "executionStatus":{"id":2,"abbreviation":"SENT","description":"Sent","version":1},
        "blotter":null,
        "tradeType":{"id":1,"abbreviation":"BUY","description":"Buy","version":1},
        "tradeOrder":{"id":50,"orderId":313688,"portfolioId":"689932cea711681c7aeda843","orderType":"BUY       ","securityId":"687597e4672efc735e8b1955","quantity":134,"quantitySent":0,"limitPrice":null,"tradeTimestamp":"2025-08-11T00:01:29.387056Z","blotter":null,"submitted":true,"version":2},
        "destination":{"id":1,"abbreviation":"ML","description":"Merrill Lynch","version":1},
        "quantityOrdered":"134.00",
        "quantityPlaced":"134.00",
        "quantityFilled":"0.00",
        "limitPrice":null,
        "version":2,
        "executionServiceId":37}
    """



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



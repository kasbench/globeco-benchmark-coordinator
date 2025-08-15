import datetime
import random
import time
from random import sample
import uuid
from locust import HttpUser, task, between, events
import requests
from queue import Queue, Empty
from gevent.lock import Semaphore

import common.portal_client as portal_client
from common.security_singleton import SecuritySingleton

security_service_url = "http://globeco-security-service:8000"
PORTFOLIOS_PER_MODEL = 10
POSITIONS_PER_MODEL = 25



# def post_portfolios(client:portal_client, data:dict) -> requests.Response:
#     portfolios = f"/api/portfolios"
#     response = client.post(portfolios, json.dumps(data), name="/api/portfolios")
#     return response

# def delete_portfolios(client:portal_client, id:str, version:int) -> requests.Response:
#     portfolios = f"/api/portfolios/{id}?version={version}"
#     response = client.delete(portfolios, name="/api/portfolios/")
#     return response

def generate_model_positions(num_positions, securities, cash=0.05, increment=0.005):
    model_securities = random.sample(securities, num_positions)
    security_allocation = 1.0 - cash
    while True:
        positions  = {security['securityId']: 0 for security in model_securities}
        overweighted_20_percent = int(num_positions * 0.2)
        weights = [1 for _ in range(num_positions - overweighted_20_percent)] + [2 for _ in range(overweighted_20_percent)]
        sum_of_targets = 0.0
        while sum_of_targets < security_allocation:
            security = random.choices(model_securities, weights=weights,k=1)[0]
            positions[security['securityId']] += increment
            sum_of_targets += increment
        if round(min(positions.values()),3) > 0:
            break    
    return {k: round(v,3) for k,v in positions.items()}
    

def create_cash_transaction(portfolio_id: int) -> list[dict]:
    # 60% of portfolios between $100,000 and $1 million.  The rest between $1 million and $4 million.
    today = datetime.date.today()
    today_formatted = today.strftime("%Y%m%d")
    
    if random.random() < 0.6:
        cash = random.randrange(100_000, 1_000_000)
    else:
        cash = random.randrange(1_000_000, 4_000_000)

    transaction = { 
        'portfolioId' : portfolio_id,
        'price': 1,
        'quantity': cash,
        'sourceId': str(uuid.uuid4()),
        'transactionDate': today_formatted,
        'transactionType': 'DEP' }
    
    return transaction

def post_transactions(client, transactions, max_post=50, url='http://globeco-portfolio-accounting-service:8087/api/v1'):
    """
    Post transactions to the portfolio accounting service.  This should be changed to use the portal client.
    """
    pos = 0
    results = []
    transactions_len = len(transactions)
    total_requested = successful = failed = 0
    while True:
        if transactions_len == 0:
            return total_requested, successful, failed, results
        if pos >= transactions_len:
            return total_requested, successful, failed, results
        next_pos = pos + max_post                   
        if next_pos > transactions_len:
            sub_transactions = transactions[pos:]
        else:
            sub_transactions = transactions[pos:next_pos]
        pos += max_post
                
        headers = {'Content-Type': 'application/json'}

        # print('Posting: ', [json.dumps(s) for s in sub_transactions])
        
        response = client.post( "/api/transactions",  json=sub_transactions)
        if response.ok:
            data = response.json() 
            # print("data: ", data)
            summary = data['summary']
            total_requested += summary['totalRequested']
            successful += summary['successful']
            failed += summary['failed']
            results.append(data)
        else:
            print(f"Error (POST): {response.status_code}, {response.reason}")

    

def split_portfolios_randomly(portfolios, num_portfolios_per_model):
    """
    Split portfolios into smaller lists of at most num_portfolios_per_model.
    Each portfolio appears in exactly one list.
    """
    # Shuffle the portfolios randomly
    shuffled_portfolios = portfolios.copy()
    random.shuffle(shuffled_portfolios)
    
    # Split into chunks
    portfolio_groups = []
    for i in range(0, len(shuffled_portfolios), num_portfolios_per_model):
        group = shuffled_portfolios[i:i + num_portfolios_per_model]
        portfolio_groups.append(group)
    
    return portfolio_groups


def post_model(client, name, positions, portfolios, url='http://globeco-order-generation-service:8088/api/v1'):
    positions = [{'security_id': k, 'target': v, 'high_drift': 0.005, 'low_drift': 0.005} for k,v in positions.items()]
    payload = {
        "name": name,
        "positions": positions,
        "portfolios": portfolios}
    headers = {'Content-Type': 'application/json'}
    # print(f"Posting model: {payload}")
    response = client.post("/api/models", json=payload, name="/api/models")
    # print(f"Response: {response}")
    if response.ok:
        return response.json()
    else:
        print(f"Error (POST): {response.status_code}, {response.reason}")
        return


def create_models(client, securities, portfolios, num_positions_per_model, num_portfolios_per_model, num_models = None,  url='http://globeco-order-generation-service:8088/api/v1'):
    """
    Create models for the given portfolios and securities.
    """
    print(f"Creating models for {len(portfolios)} portfolios")
    print(f"Number of positions per model: {num_positions_per_model}")
    print(f"Number of portfolios per model: {num_portfolios_per_model}")
    print(f"Number of models: {num_models}")    
    if num_models is None:
        num_models = len(portfolios) // num_portfolios_per_model
        print(f"Number of models: {num_models}")
    # Split portfolios into smaller random groups
    portfolio_groups = split_portfolios_randomly(portfolios, num_portfolios_per_model)
    print(f"Number of portfolio groups: {len(portfolio_groups)}")
    model_ids = []
    
    for i in range(num_models):
        print(f"Creating model {i}")
        print(f"Number of portfolios: {len(portfolios)}")
        print(f"Number of securities: {len(securities)}")
        positions = generate_model_positions(num_positions_per_model, securities)
        print(f"Positions generated: {len(positions)}")
        # Use the i-th portfolio group, cycling through if we have more models than groups
        portfolio_group = portfolio_groups[i % len(portfolio_groups)]
        model_id = str(uuid.uuid4())
        response = post_model(client, f"Model {model_id}", positions, portfolio_group, url)                    
        if response:
            model_ids.append(response['model_id'])
    
    return model_ids


class EndToEndUser(HttpUser):
    wait_time = between(0, 1)
    portfolio_ids = []
    securities = SecuritySingleton().get_securities()
    security_id = None
    model_ids = []
    rebalance_ids = []
    security_singleton = SecuritySingleton()
    new_portfolio_queue = Queue()
    new_portfolio_queue_lock = Semaphore(1)
    cash_portfolio_queue = Queue()
    cash_portfolio_queue_lock = Semaphore(1)
    model_queue = Queue()
    model_queue_lock = Semaphore(1)
    rebalance_queue = Queue()
    rebalance_queue_lock = Semaphore(1)
    order_queue = Queue()
    order_queue_lock = Semaphore(1)
    submitted_orders_queue = Queue()
    submitted_orders_queue_lock = Semaphore(1)
    execution_queue = Queue()
    execution_queue_lock = Semaphore(1)

    @task
    def post_portfolio_group(self):
        print("Posting portfolio group")
        portfolio_ids = []
        while len(portfolio_ids) < PORTFOLIOS_PER_MODEL:
            response = portal_client.post_portfolios(self.client, {
                "name": f"Test Portfolio {time.time()}",
                "dateCreated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            })
            if response.ok:
                portfolio_id = response.json()["id"]
                portfolio_ids.append(portfolio_id)
            else:
                print(f"Failed to create portfolio: {response.status_code} {response.reason}")
                print(response.text)
                raise Exception(f"Failed to create portfolio: {response.status_code} {response.reason}")
                time.sleep(1) # Might need exponential backoff here or max retries
        with self.new_portfolio_queue_lock:
            self.new_portfolio_queue.put(portfolio_ids)


    @task
    def fund_porfolios_with_cash(self):
        print("Funding portfolios with cash")
        try:
            with self.new_portfolio_queue_lock:
                portfolio_ids = self.new_portfolio_queue.get(block=False)
            funded_portfolios = []
            for portfolio_id in portfolio_ids:
                cash_transaction = create_cash_transaction(portfolio_id)
                total_requested, successful, failed, results = post_transactions(self.client, [cash_transaction])
                if successful > 0:
                    funded_portfolios.append(portfolio_id)
                else:
                    print(f"Failed to fund portfolio: {portfolio_id}")
                    time.sleep(1) # Might need exponential backoff here or max retries
            with self.cash_portfolio_queue_lock:
                self.cash_portfolio_queue.put(funded_portfolios)
        except Empty:
            print("No portfolios to fund")


    @task
    def create_models_for_portfolios(self):
        print("Creating models")
        try:
            with self.cash_portfolio_queue_lock:
                portfolio_ids = self.cash_portfolio_queue.get(block=False)
            model_id = str(uuid.uuid4())
            response = create_models(self.client, self.securities, portfolio_ids, POSITIONS_PER_MODEL, len(portfolio_ids), 1)
            if response:
                with self.model_queue_lock:
                    self.model_queue.put(response[0])
                print(f"Created model: {response[0]}")
            else:
                raise Exception(f"Failed to create models.  Status code: {response.status_code}, Reason: {response.reason}")
        except Empty:
            print("No portfolios to create models for")
                

    @task
    def rebalance_models(self): 
        print("Rebalancing models")
        try: 
            with self.model_queue_lock:
                model_id = self.model_queue.get(timeout=1)
            response = portal_client.rebalance_investment_model(self.client, model_id)
            if response.ok:
                print(f"Number of rebalances generated: {len(response.json()['rebalance_ids'])}")
                # TODO: Fix this in the backend so that we don't get duplicate rebalance ids.  This is a hack to remove duplicates.
                print(f"Rebalance ids (right before put): {response.json()['rebalance_ids']}")
                to_put = response.json()['rebalance_ids'][0]
                print(f"To put: {to_put}")
                with self.rebalance_queue_lock:
                    self.rebalance_queue.put([to_put])
            else:
                raise Exception(f"Failed to rebalance model: {model_id}.  Status code: {response.status_code}, Reason: {response.reason}")
        except Empty:
            print("No models to rebalance")

    @task
    def submit_rebalances(self):
        print("Submitting rebalances")
        try:
            with self.rebalance_queue_lock:
                rebalance_ids = self.rebalance_queue.get(block=False)
            print(f"Rebalance ids: {rebalance_ids}")
            print(f"Number of rebalances to submit: {len(rebalance_ids)}")
            for rebalance_id in rebalance_ids:
                response = portal_client.submit_rebalance(self.client, rebalance_id)
                if response.ok:
                    print(f"Submitted rebalance: {rebalance_id}")
                    with self.order_queue_lock:
                        order_ids = response.json()['submittedOrderIds']
                        for id in order_ids:
                            self.order_queue.put(id)
                else:
                    raise Exception(f"Failed to submit rebalance: {rebalance_id}.  Status code: {response.status_code}, Reason: {response.reason}")
        except Empty:
            print("No rebalances to submit")


    @task
    def submit_orders(self):
        print("Submitting orders")
        try:
            with self.order_queue_lock:
                order_id = self.order_queue.get(block=False)
            print(f"(submit_orders) Order ids {order_id}")
            # print(f"Number of orders to submit: {len(order_ids)}")
            response = portal_client.submit_order(self.client, {"orderIds": [order_id]})
            if response.ok:
                print(f"Submitted orders: {order_id}")
                with self.submitted_orders_queue_lock:
                    self.submitted_orders_queue.put(order_id)
            else:
                raise Exception(f"Failed to submit orders: {order_id}.  Status code: {response.status_code}, Reason: {response.reason}")
        except Empty:
            print("No orders to submit")
        except IndexError:
            print("No orders to submit (IndexError)")

    @task
    def submit_trades(self):
        print("Submitting trades")
        try:
            with self.submitted_orders_queue_lock:
                order_id = self.submitted_orders_queue.get(block=False)
            print(f"Order id: {order_id}")
            # Get the trade order to find the quantity
            response = portal_client.get_trade_by_order_id(self.client, order_id)
            # print(f"Response: {response.json()}")
            if response.ok:
                id = response.json()['content'][0]['id']
                quantity = response.json()['content'][0]['quantity']
                print(f"Quantity: {quantity}")
                response = portal_client.submit_trade(self.client,  id, quantity)
                if response.ok:
                    print(f"Submitted trade: {id}")   
                    execution_id = response.json()['executionServiceId']
                    with self.execution_queue_lock:
                        self.execution_queue.put(execution_id)
                else:
                    raise Exception(f"Failed to submit trade: {id}.  Status code: {response.status_code}, Reason: {response.reason}")
            else:       
                raise Exception(f"Failed to get trade order: {order_id}.  Status code: {response.status_code}, Reason: {response.reason}")
        except Empty:
            print("No orders to submit")
   

    def on_stop(self):
        print("On stop")
        print(f"Length of new_portfolio_queue: {self.new_portfolio_queue.qsize()}")
        print(f"Length of cash_portfolio_queue: {self.cash_portfolio_queue.qsize()}")
        print(f"Length of model_queue: {self.model_queue.qsize()}")
        print(f"Length of rebalance_queue: {self.rebalance_queue.qsize()}")

        # ADD CODE TO DELETE UNUSED PORTFOLIOS and MODELS

    # @task
    # def get_portfolio(self):
    #     portfolio_id = sample(self.portfolio_ids, 1)[0]
    #     response = self.client.get(f"/api/portfolios/{portfolio_id}", name="get_portfolio")
    #     if not response.ok:
    #         print(f"Failed to get portfolio: {response.status_code} {response.reason}")
    #         print(response.text)
    #     time.sleep(1)

    # def on_start(self):
    #     while not self.securities:
    #         response = portal_client.get_securities(security_service_url)        
    #         if response.ok:
    #             print(f"Got {len(response.json())} securities")
    #             self.securities= response.json()
    #         else:
    #             print(f"Failed to get securities: {response.status_code} {response.reason}")
    #         time.sleep(1)

# @events.init.add_listener
# def on_locust_init(environment, **kwargs):
#     print("On locust init")
#     securities = SecuritySingleton().get_securities()
#     print("exiting on locust init")
    

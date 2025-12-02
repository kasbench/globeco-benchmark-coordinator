import time
import uuid
from locust import HttpUser, task, between
from queue import Queue, Empty
from gevent.lock import Semaphore

import locust_common.portal_client as portal_client
from locust_common.security_singleton import SecuritySingleton

from locust_common.portal_common import create_cash_transaction, post_transactions, create_models

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


class EndToEndUser(HttpUser):
    wait_time = between(0, 1)
    portfolio_ids = []
    security_id = None
    model_ids = []
    rebalance_ids = []
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.securities = SecuritySingleton().get_securities(self.client)

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
        with self.new_portfolio_queue_lock:
            self.new_portfolio_queue.put(portfolio_ids)


    @task
    def fund_portfolios_with_cash(self):
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
                raise Exception(f"No models created.")
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
        print(f"Length of new_portfolio_queue: {self.new_portfolio_queue.qsize()}")
        print(f"Length of cash_portfolio_queue: {self.cash_portfolio_queue.qsize()}")
        print(f"Length of model_queue: {self.model_queue.qsize()}")
        print(f"Length of rebalance_queue: {self.rebalance_queue.qsize()}")




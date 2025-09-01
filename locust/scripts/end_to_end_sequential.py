import time
import uuid
import requests
from locust import HttpUser, task, between, events, constant
from queue import Queue, Empty
from gevent.lock import Semaphore

import common.portal_client as portal_client
from common.security_singleton import SecuritySingleton
from common.securities import get_securities

from common.portal_common import create_cash_transaction, post_transactions, create_models

security_service_url = "http://globeco-security-service:8000"
PORTFOLIOS_PER_MODEL = 10
POSITIONS_PER_MODEL = 25
MAX_RETRIES = 3


class EndToEndUser(HttpUser):
    # wait_time = between(1, 5)
    wait_function = constant(1)
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
        # self.securities = SecuritySingleton().get_securities(self.client)
        self.securities = get_securities()
    
    def post_portfolio_group(self):
        # print("Posting portfolio group")
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
                raise Exception(f"Failed to create portfolio: {response.status_code} {response.reason}")
        return portfolio_ids


    def fund_portfolios_with_cash(self, portfolio_ids):
        # print("Funding portfolios with cash")
        funded_portfolio_ids = []
        for portfolio_id in portfolio_ids:
            for i in range(MAX_RETRIES):
                cash_transaction = create_cash_transaction(portfolio_id)
                total_requested, successful, failed, results = post_transactions(self.client, [cash_transaction])
                if successful > 0:
                    funded_portfolio_ids.append(portfolio_id)
                    break
                else:
                    print(f"Failed to fund portfolio: {portfolio_id}")
                    backoff_time = 2 ** i # Exponential backoff based on retry attempt
                    print(f"Retrying in {backoff_time} seconds...")
                    time.sleep(backoff_time)
                raise Exception(f"Failed to fund portfolio: {portfolio_id}. Results: {results}")
        return funded_portfolio_ids
    

    def create_models_for_portfolios(self, portfolio_ids):
        # print("Creating model")
        response = create_models(self.client, self.securities, portfolio_ids, POSITIONS_PER_MODEL, len(portfolio_ids), 1)
        if response:
            model_id = response[0]
            return model_id
        else:
            raise Exception(f"No models created.")
                

    def rebalance_models(self, model_id): 
        # print("Rebalancing model")
        response = portal_client.rebalance_investment_model(self.client, model_id)
        if response.ok:
            rebalance_id = response.json()['rebalance_ids'][0]
            return rebalance_id
        else:
            raise Exception(f"Failed to rebalance model: {model_id}.  Status code: {response.status_code}, Reason: {response.reason}")

    def submit_rebalance(self, rebalance_id):
        # print("Submitting rebalance")
        # response = portal_client.submit_rebalance(self.client, rebalance_id)
        # if response.ok:
        #     order_ids = response.json()['submittedOrderIds']
        #     return order_ids
        # else:
        #     raise Exception(f"Failed to submit rebalance: {rebalance_id}.  Status code: {response.status_code}, Reason: {response.reason}")
        return portal_client.submit_rebalance(self.client, rebalance_id)

    def submit_orders(self, order_ids):
        # print("Submitting orders")
        response = portal_client.submit_order(self.client, {"orderIds": order_ids})
        if response.ok:
            successful = response.json()['successful']
            failed = response.json()['failed']
            if failed:
                raise Exception(f"Error submitting orders: Successful: {successful}, Failed: {failed}")
            return order_ids
        else:
            raise Exception(f"Failed to submit orders: {order_ids}.  Status code: {response.status_code}, Reason: {response.reason}")
        
    def submit_trades(self, submitted_order_ids):
        # print("Submitting trades")
        execution_ids = []
        for order_id in submitted_order_ids:
            # print(f"Order id: {order_id}")
            # Get the trade order to find the id and quantity
            response = portal_client.get_trade_by_order_id(self.client, order_id)
            if response.ok:
                id = response.json()['content'][0]['id']
                quantity = response.json()['content'][0]['quantity']
                response = portal_client.submit_trade(self.client,  id, quantity)
                if response.ok:
                    # print(f"Submitted trade: {id}")   
                    execution_id = response.json()['executionServiceId']
                    execution_ids.append(execution_id)
                else:
                    raise Exception(f"Failed to submit trade: {id}.  Status code: {response.status_code}, Reason: {response.reason}")
            else:       
                raise Exception(f"Failed to get trade order: {order_id}.  Status code: {response.status_code}, Reason: {response.reason}")


    @task
    def run_sequential(self):
        portfolio_ids = self.post_portfolio_group()
        funded_portfolio_ids = self.fund_portfolios_with_cash(portfolio_ids)
        model_id = self.create_models_for_portfolios(funded_portfolio_ids)
        rebalance_id = self.rebalance_models(model_id)
        order_ids = self.submit_rebalance(rebalance_id)
        # Process order_ids in batches of max_orders
        max_orders = 25
        for i in range(0, len(order_ids), max_orders):
            try:
                batch_order_ids = order_ids[i:i+max_orders]
                submitted_order_ids = self.submit_orders(batch_order_ids)  # this is where we are getting dupes
                self.submit_trades(submitted_order_ids)
            except Exception as e:
                print(f"Error submitting orders for batch {i}: {e}")
                continue

    # def on_stop(self):
    #     # TODO: Add call to portfolio accounting CLI (must be once for the entire batch)    
    #     # print("On stop")
    #     print(f"Length of new_portfolio_queue: {self.new_portfolio_queue.qsize()}")
    #     print(f"Length of cash_portfolio_queue: {self.cash_portfolio_queue.qsize()}")
    #     print(f"Length of model_queue: {self.model_queue.qsize()}")
    #     print(f"Length of rebalance_queue: {self.rebalance_queue.qsize()}")


    # @events.test_stop.add_listener
    def on_test_stop(environment, **kwargs):
        print("Sending allocations to Portfolio Accounting")
        host = environment.host
        url = f"{host}/api/allocations/executions/send"
        print(f"URL: {url}")
        response = requests.post(url, data={})
        if response.ok:
            print("Allocations sent to Portfolio Accounting")
            print(response.json())
        else:
            print(f"Failed to send allocations to Portfolio Accounting.  Status code: {response.status_code}, Reason: {response.reason}") 

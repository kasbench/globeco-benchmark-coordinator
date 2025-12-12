import time
import uuid
import requests
import random
import asyncio

from locust import HttpUser, task, between, events, constant, FastHttpUser
from queue import Queue, Empty
from gevent.lock import Semaphore

import resource
try:
    resource.setrlimit(resource.RLIMIT_NOFILE, (10240, 9223372036854775807))
except:
    # Throws an exception on Ubuntu.  Helpful for Mac
    pass

import common.portal_client as portal_client
from common.security_singleton import SecuritySingleton
from common.securities import get_securities

from common.portal_common import create_cash_transaction, post_transactions, create_models, post_portfolio_group

security_service_url = "http://globeco-security-service:8000"
PORTFOLIOS_PER_MODEL = 10
POSITIONS_PER_MODEL = 25
MAX_RETRIES = 3


class EndToEndUser(HttpUser):
    wait_time = between(5, 20)
    
    counter = 0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # self.securities = SecuritySingleton().get_securities(self.client)
        self.securities = get_securities()

    def on_start(self):
        """This method is called when the User is spawned."""
        time.sleep(random.uniform(1, 45))
        

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
            return response
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
            # print("Submitted order results:")
            # print(response.json())
            # print()
            successful = response.json()['successful']
            failed = response.json()['failed']
            if failed:
                raise Exception(f"Error submitting orders: Successful: {successful}, Failed: {failed}")
            trade_order_ids = []
            for order in response.json()['results']:
                trade_order_ids.append(order['tradeOrderId'])
            return trade_order_ids
        else:
            raise Exception(f"Failed to submit orders: {order_ids}.  Status code: {response.status_code}, Reason: {response.reason}")
        

    def submit_trades(self, submitted_order_ids):
        # print("Submitting trades")
        execution_ids = []
        response = portal_client.submit_trade(self.client, submitted_order_ids, [1] * len(submitted_order_ids))
        if not response.ok:
            print(f"Failed to submit trades: {submitted_order_ids}.  Status code: {response.status_code}, Reason: {response.reason}")
            raise Exception(f"Failed to submit trades: {submitted_order_ids}.  Status code: {response.status_code}, Reason: {response.reason}")
        

    def submit_trades_slow(self, submitted_order_ids):
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
        time.sleep(random.uniform(1, 5))
        # Create a group of portfolios
        portfolio_ids = post_portfolio_group(self.client)
        time.sleep(random.uniform(1, 5))
        # Get each of them
        for portfolio_id in portfolio_ids:
            time.sleep(random.uniform(0, 2))
            portal_client.get_portfolio(self.client, portfolio_id)
        # Fund the portfolios
        funded_portfolio_ids = self.fund_portfolios_with_cash(portfolio_ids)
        # Create models for each funded portfolio
        model_ids = self.create_models_for_portfolios(funded_portfolio_ids)
        time.sleep(random.uniform(1, 5))
        # Get the models
        for model_id in model_ids:
            time.sleep(random.uniform(0, 2))
            portal_client.get_investment_model(self.client, model_id)
        # Rebalance one of the models
        time.sleep(random.uniform(1, 5))
        rebalance_id = self.rebalance_models(model_ids[0])
        # Submit the rebalance (send to the Order Service)
        time.sleep(random.uniform(1, 5))
        order_ids = self.submit_rebalance(rebalance_id)
        # Process order_ids in batches of max_orders
        max_orders = 10
        for i in range(0, len(order_ids), max_orders):
            try:
                batch_order_ids = order_ids[i:i+max_orders]
                time.sleep(random.uniform(0, 2))
                # Submit order (send to Trading Service)
                submitted_order_ids = self.submit_orders(batch_order_ids) 
                time.sleep(random.uniform(0, 2))
                # Submit trades (send to Execution Service)
                self.submit_trades(submitted_order_ids)
            except Exception as e:
                print(f"Error submitting orders for batch {i}: {e}")
                continue
        # Get next 10 orders
        time.sleep(random.uniform(0, 2))
        portal_client.get_orders(self.client, offset=self.counter*10, limit=10)
        # Get the next 10 trades
        time.sleep(random.uniform(0, 2))
        portal_client.get_trades(self.client, offset=self.counter*10, limit=10)
        self.counter += 1
        # Get executions for the first portfolio id
        time.sleep(random.uniform(0, 2))
        portal_client.get_executions(self.client, portfolio_id=portfolio_ids[0])



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

import time
import uuid
import requests
import random
import asyncio
import logging

from locust import HttpUser, task, between, events, constant, FastHttpUser
from queue import Queue, Empty
from gevent.lock import Semaphore
import sqlite3

import resource
try:
    resource.setrlimit(resource.RLIMIT_NOFILE, (10240, 9223372036854775807))
except:
    # Throws an exception on Ubuntu.  Helpful for Mac
    pass

import locust_common.portal_client as portal_client
from locust_common.security_singleton import SecuritySingleton
from locust_common.securities import securities

from locust_common.portal_common import create_cash_transaction, post_transactions, create_models, post_portfolio_group

PORTFOLIOS_PER_MODEL = 10
POSITIONS_PER_MODEL = 25
MAX_RETRIES = 3


# Configure logging
logging.basicConfig(level=logging.INFO)


@events.init_command_line_parser.add_listener
def _(parser):
    parser.add_argument("--sqlite_db", type=str, default="sqlite.db", help="Path to sqlite database")




class BenchmarkUser(HttpUser):
    wait_time = between(5, 20)
    
    counter = 0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Cache static list of securities
        self.securities = securities

    def on_start(self):
        # Assign a unique ID (UUID4) to each user instance
        self.user_id = str(uuid.uuid4())
        logging.info(f"User {self.user_id} started")
        
        # wait_time does not apply to the first call.  This assures that the first API calls are staggered
        # even if all users start at the same time.
        time.sleep(random.uniform(1, 30))

        self.sqlite_db = self.environment.parsed_options.sqlite_db
        self.conn = sqlite3.connect(self.sqlite_db)

        cursor = self.conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS logs (
                user_id TEXT,
                request_type TEXT,
                name TEXT,
                response_time REAL,
                response_length INTEGER,
                response TEXT,
                status_code TEXT,
                reason TEXT,
                exception TEXT,
                start_time REAL,
                url TEXT
            )
        ''')
    

    def context(self):
        return {
            "user_id": self.user_id,
            "conn": self.conn
        }

    
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

    @events.request.add_listener
    def on_request(
        request_type,
        name,
        response_time,
        response_length,
        response,
        context,
        exception,
        start_time,
        url,
        **kwargs
    ):
        """
        A handler that runs after every request.
        """
        if context and "user_id" in context:
            user_id = context["user_id"]
        else:
            user_id = "Unknown"
            
        if exception:
            logging.error(f"Request to {name} failed: {exception}")
        # else:
        #     logging.info(f"Name: {name}, User: {user_id}, Response time: {response_time}, Start time: {start_time}, URL: {url}")

        if context and "conn" in context:
            conn = context["conn"]
            cursor = conn.cursor()  
            cursor.execute(
                "INSERT INTO logs (user_id, request_type, name, response_time, response_length, response, status_code, reason, exception, start_time, url) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, request_type, name, response_time, response_length, str(response), response.status_code, response.reason, str(exception), start_time, url)
            )
            conn.commit()

      
        


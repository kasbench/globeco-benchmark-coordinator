import time
from random import sample
from locust import HttpUser, task, between
import common.portal_client as portal_client


class PortfolioUser(HttpUser):
    wait_time = between(1, 5)

    portfolio_ids = []



    @task
    def get_portfolio(self):
        portfolio_id = sample(self.portfolio_ids, 1)[0]
        response = self.client.get(f"/api/portfolios/{portfolio_id}", name="get_portfolio")
        if not response.ok:
            print(f"Failed to get portfolio: {response.status_code} {response.reason}")
            print(response.text)
        time.sleep(1)

    def on_start(self):
        while not self.portfolio_ids:
            response = self.client.get ("/api/portfolios", name="get_portfolios")
            if response.ok:
                portfolios = response.json()
                self.portfolio_ids = [portfolio["id"] for portfolio in portfolios]
            else:
                print(f"Failed to get portfolios: {response.status_code} {response.reason}")
                print(response.text)
            time.sleep(1)



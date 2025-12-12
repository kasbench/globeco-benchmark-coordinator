import random
import resource


from locust import HttpUser, task, between, tag

from common.portal_common import post_portfolio_group
from common.portal_client import get_portfolio, put_portfolios

PORTFOLIO_TAG = "globeco-portfolio-service"

try:
    resource.setrlimit(resource.RLIMIT_NOFILE, (10240, 9223372036854775807))
except:
    # Throws an exception on Ubuntu.  Helpful for Mac
    pass


class CalibrationUser(HttpUser):
    wait_time = between(1, 2)
    portfolio_ids = []

    def on_start(self):
        # Initialize data based on tags
        if self.environment.parsed_options.tags:
            if PORTFOLIO_TAG in self.environment.parsed_options.tags:
                self.portfolio_ids = post_portfolio_group(self.client)

        # If no tags have been passed, the default behavior is to load data for all tags    
        else:
            self.portfolio_ids = post_portfolio_group(self.client)


    @task(1)
    @tag(PORTFOLIO_TAG)
    def create_portfolios(self):
        self.portfolio_ids.extend(post_portfolio_group(self.client))


    @task(10)
    @tag(PORTFOLIO_TAG)
    def get_portfolios(self):
        if self.portfolio_ids:
            portfolio_id = random.choice(self.portfolio_ids)
            response = get_portfolio(self.client, portfolio_id)
            if response.ok:
                data = response.json()
                id = data['id']
                name = data['name']
                date_created = data['dateCreated']
                version = data['version']

                parts = name.rsplit('-', 1)
                prefix = parts[0]
                number = int(parts[1])
                new_number = number + 1
                name = f"{prefix}-{new_number}"   
                put_portfolios(self.client, id, {"portfolioId": id, "name": name, "dateCreated": date_created, "version": version})
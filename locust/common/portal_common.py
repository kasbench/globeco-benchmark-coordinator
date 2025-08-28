import datetime
import random
import uuid


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

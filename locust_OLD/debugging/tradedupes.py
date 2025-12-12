import sys
import re

PATTERN = re.compile(r'Creating trade order: (\d+)')

order_ids = {}
matched = 0
duplicates = 0
for line in sys.stdin:
    if match := PATTERN.search(line):
        matched += 1
        order_id = int(match.group(1))
        if order_ids.get(order_id):
            print(f'Duplicate order id: {order_id}')  
            duplicates += 1
        # else:
        #     print(".", end='')
        order_ids[order_id] = 1

print(f'\nMatched: {matched}')
print(f'Duplicates: {duplicates}')

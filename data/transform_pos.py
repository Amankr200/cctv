"""Transform raw POS CSV to normalized format for the pipeline."""
import csv
from datetime import datetime

INPUT_FILE = r'..\..\Brigade_Bangalore_10_April_26 (1)bc6219c.csv'
OUTPUT_FILE = 'pos_transactions.csv'

seen_orders = {}

with open(INPUT_FILE, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        order_id = row['order_id'].strip()
        if order_id in seen_orders:
            # Aggregate: add to basket value
            seen_orders[order_id]['basket_value_inr'] += float(row.get('total_amount', 0) or 0)
            continue
        
        # Parse date + time
        date_str = row['order_date'].strip()  # DD-MM-YYYY
        time_str = row['order_time'].strip()  # HH:MM:SS
        try:
            dt = datetime.strptime(f"{date_str} {time_str}", "%d-%m-%Y %H:%M:%S")
            iso_ts = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            continue
        
        seen_orders[order_id] = {
            'store_id': 'STORE_BLR_002',
            'transaction_id': f'TXN_{order_id}',
            'timestamp': iso_ts,
            'basket_value_inr': float(row.get('total_amount', 0) or 0)
        }

# Write normalized CSV
with open(OUTPUT_FILE, 'w', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=['store_id', 'transaction_id', 'timestamp', 'basket_value_inr'])
    writer.writeheader()
    for order in sorted(seen_orders.values(), key=lambda x: x['timestamp']):
        writer.writerow(order)

print(f"Wrote {len(seen_orders)} unique transactions to {OUTPUT_FILE}")

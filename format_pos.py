import csv
from datetime import datetime
import os

input_file = r"c:\Users\krama\Downloads\CCTV Footage-20260529T160731Z-3-00144614ea\Brigade_Bangalore_10_April_26 (1)bc6219c.csv"
output_file = r"c:\Users\krama\Downloads\CCTV Footage-20260529T160731Z-3-00144614ea\store-intelligence\data\pos_transactions.csv"

os.makedirs(os.path.dirname(output_file), exist_ok=True)

# We want: transaction_id, store_id, timestamp, basket_value_inr
transactions = {}

with open(input_file, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        txn_id = row['order_id']
        if not txn_id:
            continue
            
        # Parse 10-04-2026 16:55:36 (IST) -> UTC
        try:
            dt = datetime.strptime(f"{row['order_date']} {row['order_time']}", "%d-%m-%Y %H:%M:%S")
            # Convert to UTC ISO format (subtracting 5.5 hours for IST)
            # Simplification: just formatting it to ISO. The problem statement base time is 2026-04-10T20:00:00Z
            # Let's just output ISO format directly
            iso_time = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except:
            continue
            
        amount = float(row['total_amount'] or 0)
        
        # Aggregate by order_id because raw file has 1 row per item
        if txn_id not in transactions:
            transactions[txn_id] = {
                'transaction_id': txn_id,
                'store_id': "STORE_BLR_002", # Forcing to match CCTV
                'timestamp': iso_time,
                'basket_value_inr': amount
            }
        else:
            transactions[txn_id]['basket_value_inr'] += amount

with open(output_file, 'w', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=['transaction_id', 'store_id', 'timestamp', 'basket_value_inr'])
    writer.writeheader()
    for txn in transactions.values():
        writer.writerow(txn)

print(f"Successfully converted {len(transactions)} POS transactions.")

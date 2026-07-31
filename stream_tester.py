import asyncio
import csv
import json
import time
import argparse
import aiohttp

async def submit_transaction(session, url, payload):
    try:
        async with session.post(url, json=payload) as response:
            return response.status
    except Exception as e:
        return str(e)

async def main(csv_path, target_url, concurrency, limit):
    print(f"Loading data from {csv_path}...")
    transactions = []
    
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            if limit and i >= limit:
                break
            
            # Map CSV fields to TransactionRequest format expected by Gateway
            payload = {
                "txn_id": row.get("TransactionID", f"TXN_{time.time()}"),
                "account_id": row.get("AccountID", "ACC_001"),
                "amount": float(row.get("TransactionAmount", 0.0)),
                # Adding some mock features to make it interesting
                "rolling_spend_10m": float(row.get("TransactionAmount", 0.0)) * 1.5, 
                "txn_count_10m": 1,
                "bitmask": 0,
                "is_fraudulent": False
            }
            transactions.append(payload)

    print(f"Loaded {len(transactions)} transactions.")
    print(f"Starting ingestion to {target_url} with concurrency {concurrency}...")
    
    start_time = time.time()
    
    connector = aiohttp.TCPConnector(limit=concurrency)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = []
        for i, payload in enumerate(transactions):
            task = asyncio.create_task(submit_transaction(session, target_url, payload))
            tasks.append(task)
            
        # Optional: chunking tasks to avoid memory issues if limit is huge
        results = await asyncio.gather(*tasks)

    end_time = time.time()
    duration = end_time - start_time
    success_count = sum(1 for r in results if r == 200)
    error_count = len(results) - success_count
    
    print("\n--- Ingestion Report ---")
    print(f"Total Sent:     {len(transactions)}")
    print(f"Success (200):  {success_count}")
    print(f"Errors/Failed:  {error_count}")
    print(f"Time Taken:     {duration:.2f} seconds")
    print(f"Throughput:     {len(transactions) / duration:.2f} txns/sec")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="High-frequency transaction streaming test script")
    parser.add_argument("--csv", type=str, default="data/ieee_transactions.csv", help="Path to CSV file")
    parser.add_argument("--url", type=str, default="http://localhost:8080/submit", help="Gateway submit endpoint")
    parser.add_argument("--concurrency", type=int, default=50, help="Number of concurrent requests")
    parser.add_argument("--limit", type=int, default=1000, help="Limit number of transactions to send (0 for all)")
    args = parser.parse_args()
    
    asyncio.run(main(args.csv, args.url, args.concurrency, args.limit))

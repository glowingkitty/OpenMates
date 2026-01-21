#!/usr/bin/env python3
"""
Script to backfill historical server-wide statistics into Directus global stats models.
Optimized for high-volume environments (millions of messages/usage entries).
"""

import asyncio
import logging
import sys
import hashlib
import time
from datetime import datetime, date, timedelta
from collections import defaultdict
from typing import Dict, Any, List, Optional

# Add the backend directory to the Python path
sys.path.insert(0, '/app/backend')

from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.utils.secrets_manager import SecretsManager

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('backfill_stats')

# Optimized constants for scale
BATCH_SIZE_LARGE = 5000  # For simple metadata scans
BATCH_SIZE_DECRYPT = 500 # For encryption-heavy tasks
CONCURRENCY_LIMIT = 50

async def backfill():
    sm = SecretsManager()
    await sm.initialize()
    
    cache_service = CacheService()
    encryption_service = EncryptionService(cache_service=cache_service)
    directus_service = DirectusService(cache_service=cache_service, encryption_service=encryption_service)
    
    try:
        logger.info("Starting production-grade stats backfill...")
        
        # 1. Establish User Map and Current Liability
        user_map: Dict[str, str] = {} # hash -> vault_key_id
        total_liability = 0
        total_users_count = 0
        semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)

        async def decrypt_bal(val, v_id):
            async with semaphore:
                try:
                    res = await encryption_service.decrypt_with_user_key(val, v_id)
                    return int(res) if res and res.isdigit() else 0
                except Exception: return 0

        logger.info("Step 1: Mapping users and calculating real-time liability...")
        offset = 0
        while True:
            users = await directus_service.get_items('users', params={
                'fields': 'id,vault_key_id,encrypted_credit_balance,is_admin',
                'limit': BATCH_SIZE_DECRYPT,
                'offset': offset
            })
            if not users: break
            
            tasks = []
            for u in users:
                if u.get('is_admin'): continue
                total_users_count += 1
                u_id = u.get('id')
                v_key_id = u.get('vault_key_id')
                if u_id and v_key_id:
                    u_hash = hashlib.sha256(u_id.encode()).hexdigest()
                    user_map[u_hash] = v_key_id
                    if u.get('encrypted_credit_balance'):
                        tasks.append(decrypt_bal(u['encrypted_credit_balance'], v_key_id))
            
            if tasks:
                results = await asyncio.gather(*tasks)
                total_liability += sum(results)
            
            offset += BATCH_SIZE_DECRYPT
            if offset % 5000 == 0: logger.info(f"  {offset} users mapped...")

        logger.info(f"Liability established: {total_liability} credits. Total users: {total_users_count}. Updating hot cache...")
        await cache_service.set_total_liability(total_liability)

        # 2. Aggregation Structure
        daily_records = defaultdict(lambda: {
            "new_users_registered": 0,
            "new_users_finished_signup": 0,
            "income_eur_cents": 0,
            "credits_sold": 0,
            "credits_used": 0,
            "messages_sent": 0,
            "chats_created": 0,
            "embeds_created": 0,
            "liability_total": 0,
            "active_subscriptions": 0,
            "total_regular_users": 0
        })

        # 3. Processing Engagement via Time-Windows
        end_date = date.today()
        current_date = date(2024, 1, 1) 
        
        while current_date <= end_date:
            next_month = (current_date.replace(day=28) + timedelta(days=4)).replace(day=1)
            start_ts = int(time.mktime(current_date.timetuple()))
            end_ts = int(time.mktime(next_month.timetuple()))
            
            for coll, field in [('chats', 'chats_created'), ('messages', 'messages_sent'), ('embeds', 'embeds_created')]:
                logger.info(f"Processing {coll} for {current_date.strftime('%Y-%m')}...")
                offset = 0
                while True:
                    items = await directus_service.get_items(coll, params={
                        'fields': 'created_at',
                        'filter': {
                            '_and': [
                                {'created_at': {'_gte': start_ts}},
                                {'created_at': {'_lt': end_ts}}
                            ]
                        },
                        'limit': 1000,
                        'offset': offset
                    })
                    if not items: break
                    for item in items:
                        ts = item.get('created_at')
                        if ts:
                            try:
                                d_str = datetime.fromtimestamp(ts).strftime('%Y-%m-%d')
                                daily_records[d_str][field] += 1
                            except Exception: pass
                    offset += 1000
            
            current_date = next_month

        # 4. Processing Invoices (Financials)
        logger.info("Step 4: Processing invoices...")
        async def process_inv(inv):
            u_hash = inv.get('user_id_hash')
            v_id = user_map.get(u_hash)
            if not v_id: return None
            async with semaphore:
                try:
                    amt_str = await encryption_service.decrypt_with_user_key(inv['encrypted_amount'], v_id)
                    cred_str = await encryption_service.decrypt_with_user_key(inv['encrypted_credits_purchased'], v_id)
                    if amt_str and cred_str:
                        return {"date": inv['date'][:10], "amount": int(amt_str), "credits": int(cred_str), "u_hash": u_hash}
                except Exception: pass
            return None

        offset = 0
        finished_signup_users = set()
        while True:
            invoices = await directus_service.get_items('invoices', params={
                'fields': 'user_id_hash,date,encrypted_amount,encrypted_credits_purchased,refund_status',
                'limit': BATCH_SIZE_DECRYPT,
                'offset': offset
            })
            if not invoices: break
            tasks = [process_inv(inv) for inv in invoices if inv.get('refund_status') != 'completed']
            results = await asyncio.gather(*tasks)
            for r in results:
                if r:
                    daily_records[r['date']]["income_eur_cents"] += r['amount']
                    daily_records[r['date']]["credits_sold"] += r['credits']
                    if r['u_hash'] not in finished_signup_users:
                        finished_signup_users.add(r['u_hash'])
                        daily_records[r['date']]["new_users_finished_signup"] += 1
            offset += BATCH_SIZE_DECRYPT

        # 5. Persistence
        logger.info("Step 5: Persisting aggregated results...")
        sorted_dates = sorted(daily_records.keys())
        # We can't easily backfill historical 'total_regular_users' without registration dates,
        # so we'll just set it for today and maybe use total count for all.
        for d_str in sorted_dates:
            daily_records[d_str]["date"] = d_str
            # Final snapshot for today
            if d_str == date.today().isoformat():
                daily_records[d_str]["liability_total"] = total_liability
                daily_records[d_str]["total_regular_users"] = total_users_count
            
            existing = await directus_service.analytics.get_server_stats_daily(d_str)
            if existing:
                await directus_service.analytics.update_server_stats_daily(existing["id"], daily_records[d_str])
            else:
                await directus_service.analytics.create_server_stats_daily(daily_records[d_str])

        # 6. Monthly Aggregation
        logger.info("Step 6: Aggregating monthly data...")
        months = sorted(list(set(d[:7] for d in sorted_dates)))
        from backend.core.api.app.tasks.server_stats_tasks import update_monthly_stats
        class MockTask:
            def __init__(self, ds): self.directus_service = ds
            async def cleanup_services(self): pass
            async def initialize_services(self): pass
        for m in months:
            await update_monthly_stats(MockTask(directus_service), m)

        logger.info(f"SUCCESS: Backfilled {len(sorted_dates)} days across {len(months)} months.")

    except Exception as e:
        logger.error(f"Backfill failed: {e}", exc_info=True)
    finally:
        await sm.aclose()
        await directus_service.close()

if __name__ == "__main__":
    asyncio.run(backfill())
